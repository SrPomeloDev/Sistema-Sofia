"""
lifecycle.py — Inicialización y shutdown del módulo Camiones.
"""

import logging
import asyncio

from modules.camiones.db.database import (
    init_db,
    obtener_total_camiones_count,
    obtener_todos_camiones,
    upsert_camiones_desde_sheets,
    guardar_camiones_bulk,
    CamionDb,
    async_session_factory,
)
from modules.camiones.config import settings
from modules.camiones.services.sheets import sheets_client
from modules.camiones.routes import update_queue
from modules.camiones.services.excel_parser import parse_excel_camiones

logger = logging.getLogger(__name__)
SYNC_INTERVAL = 30
auto_sync_task = None

# ── Lógica de Sincronización ───────────────────────────────────────────
async def sincronizar_desde_sheets():
    """
    Lee todas las filas de Google Sheets y las vuelca en SQLite.
    Soporta tanto el formato de Apps Script (JSON objects) como raw arrays.
    """
    logger.info("Iniciando sincronización desde Google Sheets...")
    result = await sheets_client.read_all_rows()

    if not result.get("success"):
        logger.warning("Error al leer Google Sheets: %s", result.get("error"))
        return False

    rows = result.get("data", [])
    if not rows or len(rows) == 0:
        logger.warning("Google Sheets vacío.")
        return False

    camiones_sincronizados = []

    # Recuperar datos existentes para preservar sistema_camion
    existentes_local = {c.placa: c for c in await obtener_todos_camiones()}

    # Si rows[0] es un dict, viene de Apps Script (ya parseado)
    if rows and isinstance(rows[0], dict):
        for obj in rows:
            placa = str(obj.get("placa", "")).strip()
            if not placa:
                continue
            entry = {
                "fila_id": obj.get("fila_id", 0),
                "nro": str(obj.get("nro", "")),
                "placa": placa,
                "estado_trabajo": str(obj.get("estado_trabajo", "Fijo")),
                "tipo_combustible": str(obj.get("tipo_combustible", "GAS-GASOLINA")),
                "costo_flete": float(obj.get("costo_flete", 0)),
                "sucursal": str(obj.get("sucursal", "")),
                "capacidad_kg": int(obj.get("capacidad_kg", 0)),
                "capacidad_maples": int(obj.get("capacidad_maples", 0)),
                "capacidad_util_kg": float(obj.get("capacidad_util_kg", 0)),
            }
            if placa in existentes_local:
                entry["sistema_camion"] = existentes_local[placa].sistema_camion
                entry["estado_servicio"] = existentes_local[placa].estado_servicio
            else:
                entry["sistema_camion"] = obj.get("sistema_camion") or "SIN INFORMACIÓN"
                entry["estado_servicio"] = obj.get("estado_servicio") or "EN SERVICIO"
            camiones_sincronizados.append(entry)

    # Si viene como raw arrays (gspread fallback)
    elif rows and isinstance(rows[0], list):
        for idx, row in enumerate(rows[1:], start=2):
            if not row or not any(row):
                continue
            padded = row + [""] * (10 - len(row))
            placa = str(padded[1]).strip()
            if not placa:
                continue

            def to_float(v, d=0.0):
                try: return float(str(v).replace(",", "."))
                except: return d
            def to_int(v, d=0):
                try: return int(float(str(v).replace(",", ".")))
                except: return d

            entry = {
                "fila_id": idx,
                "nro": str(padded[0]).strip(),
                "placa": placa,
                "estado_trabajo": str(padded[2]).strip() or "Fijo",
                "tipo_combustible": str(padded[3]).strip() or "GAS-GASOLINA",
                "costo_flete": to_float(padded[4]),
                "sucursal": str(padded[5]).strip(),
                "capacidad_kg": to_int(padded[6]),
                "capacidad_maples": to_int(padded[7]),
                "capacidad_util_kg": to_float(padded[8]),
            }
            sistema = str(padded[9]).strip() if len(padded) > 9 else ""
            servicio = str(padded[10]).strip() if len(padded) > 10 else ""
            if placa in existentes_local:
                entry["sistema_camion"] = existentes_local[placa].sistema_camion
                entry["estado_servicio"] = existentes_local[placa].estado_servicio
            else:
                entry["sistema_camion"] = sistema or "SIN INFORMACIÓN"
                entry["estado_servicio"] = servicio or "EN SERVICIO"
            camiones_sincronizados.append(entry)

    if camiones_sincronizados:
        await upsert_camiones_desde_sheets(camiones_sincronizados)
        logger.info("Sincronizados %d camiones desde Google Sheets a SQLite (upsert)", len(camiones_sincronizados))
        return True
    return False

_push_task = None

BATCH_SIZE = 10

async def inicializar_sheets_con_local():
    """Sube datos locales a Google Sheets en batches concurrentes."""
    logger.info("Iniciando push a Google Sheets...")
    from modules.camiones.services.sheets import HEADERS_LIST
    camiones = await obtener_todos_camiones()

    # Recalcular nro como contador secuencial por sucursal y persistir
    from sqlalchemy import text
    suc_counters = {}
    for c in camiones:
        s = c.sucursal
        suc_counters[s] = suc_counters.get(s, 0) + 1
        c.nro = str(suc_counters[s])
    async with async_session_factory() as session:
        for c in camiones:
            await session.execute(
                text("UPDATE camiones SET nro = :nro WHERE fila_id = :fid"),
                {"nro": c.nro, "fid": c.fila_id}
            )
        await session.commit()

    rows = []
    for c in camiones:
        rows.append([
            str(c.nro or ""),
            str(c.placa),
            str(c.estado_trabajo),
            str(c.tipo_combustible),
            str(c.costo_flete),
            str(c.sucursal),
            str(c.capacidad_kg),
            str(c.capacidad_maples),
            str(c.capacidad_util_kg),
            str(c.sistema_camion),
        ])

    # Intentar un solo request (setAll)
    result = await sheets_client.set_all_rows(HEADERS_LIST, rows)
    if result.get("success"):
        logger.info("Push completado en 1 request: %d filas.", len(rows))
        return

    logger.info("setAll no disponible, usando clear + batches concurrentes...")
    await sheets_client.clear_sheet()

    total = len(rows)
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        tasks = []
        for j, row in enumerate(batch):
            fila = start + j + 2
            tasks.append(sheets_client.update_row(fila, row))
        await asyncio.gather(*tasks)
        logger.info("  Batch %d/%d completado", start // BATCH_SIZE + 1, (total + BATCH_SIZE - 1) // BATCH_SIZE)

    logger.info("Push completado: %d filas actualizadas en %d batches.", total, (total + BATCH_SIZE - 1) // BATCH_SIZE)

async def push_to_sheets_background():
    """Corre push-to-sheets en un task separado."""
    global _push_task
    try:
        await inicializar_sheets_con_local()
    except Exception as e:
        logger.error("Push a Sheets falló: %s", e)
    finally:
        _push_task = None

async def auto_sync_loop():
    """
    Cada SYNC_INTERVAL segundos trae los cambios de Google Sheets a SQLite.
    Así, si alguien edita una celda directamente en Sheets, el dashboard
    se entera sin necesidad de reiniciar ni hacer clic en Sync.
    """
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        if not sheets_client.enabled:
            continue
        try:
            result = await sheets_client.read_all_rows()
            if not result.get("success"):
                continue
            rows = result.get("data", [])
            if not rows:
                continue
            camiones = []
            existentes_local = {c.placa: c for c in await obtener_todos_camiones()}
            for obj in rows:
                placa = str(obj.get("placa", "")).strip()
                if not placa:
                    continue
                entry = {
                    "fila_id": obj.get("fila_id", 0),
                    "nro": str(obj.get("nro", "")),
                    "placa": placa,
                    "estado_trabajo": str(obj.get("estado_trabajo", "Fijo")),
                    "tipo_combustible": str(obj.get("tipo_combustible", "GAS-GASOLINA")),
                    "costo_flete": float(obj.get("costo_flete", 0)),
                    "sucursal": str(obj.get("sucursal", "")),
                    "capacidad_kg": int(obj.get("capacidad_kg", 0)),
                    "capacidad_maples": int(obj.get("capacidad_maples", 0)),
                    "capacidad_util_kg": float(obj.get("capacidad_util_kg", 0)),
                }
                if placa in existentes_local:
                    entry["sistema_camion"] = existentes_local[placa].sistema_camion
                    entry["estado_servicio"] = existentes_local[placa].estado_servicio
                else:
                    entry["sistema_camion"] = obj.get("sistema_camion") or "SIN INFORMACIÓN"
                    entry["estado_servicio"] = obj.get("estado_servicio") or "EN SERVICIO"
                camiones.append(entry)
            await upsert_camiones_desde_sheets(camiones)
            logger.debug("Auto-sync completado: %d camiones upsertados", len(camiones))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Error en auto-sync periódico: %s", e)

async def init_module():
    """Called during app startup"""
    global auto_sync_task
    logger.info("Iniciando módulo Camiones...")
    
    await init_db()
    
    total_locales = await obtener_total_camiones_count()
    if total_locales == 0:
        excel_path = settings.bootstrap_excel
        logger.info("SQLite vacío. Importando desde Excel: %s", excel_path)
        records = parse_excel_camiones(excel_path)
        if records:
            await guardar_camiones_bulk(records)
            logger.info("Importación inicial: %d registros", len(records))
    
    await sheets_client.initialize()
    
    if sheets_client.enabled:
        try:
            result = await sheets_client.read_all_rows()
            if result.get("success") and result.get("data"):
                await sincronizar_desde_sheets()
            elif result.get("success") and not result.get("data"):
                await inicializar_sheets_con_local()
        except Exception as e:
            logger.warning("Sync inicial falló (no crítico): %s", e)
    
    await update_queue.start()
    
    auto_sync_task = asyncio.create_task(auto_sync_loop())
    logger.info("Módulo Camiones listo.")

async def shutdown_module():
    """Called during app shutdown"""
    global auto_sync_task
    if auto_sync_task:
        auto_sync_task.cancel()
        try:
            await auto_sync_task
        except asyncio.CancelledError:
            pass
    await update_queue.stop()
    logger.info("Módulo Camiones detenido.")
