"""
lifecycle.py — Inicialización y shutdown del módulo Camiones.
"""

import logging
import asyncio
import os

from modules.camiones.db.database import (
    init_db,
    obtener_total_camiones_count,
    obtener_todos_camiones,
    upsert_camiones_desde_sheets,
    guardar_camiones_bulk,
    CamionDb,
    async_session_factory,
    asignar_rutas_desde_madres,
    poblar_ruta_madre_desde_ruta,
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
            ruta_val = str(obj.get("ruta", "")).strip()
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
            if ruta_val:
                entry["ruta"] = ruta_val
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
            padded = row + [""] * max(0, 11 - len(row))
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
        # Eliminar locales que ya no están en sheets
        placas_en_sheets = {c["placa"] for c in camiones_sincronizados}
        from modules.camiones.db.database import async_session_factory as local_session, CamionDb
        from sqlalchemy import select, delete
        async with local_session() as session:
            todos_locales = await session.execute(select(CamionDb.placa, CamionDb.fila_id))
            for placa, fid in todos_locales:
                if placa not in placas_en_sheets:
                    await session.execute(delete(CamionDb).where(CamionDb.fila_id == fid))
                    logger.info("Eliminado localmente camión %s (fila %s) que ya no está en sheets", placa, fid)
            await session.commit()
        return True
    return False

_push_task = None

BATCH_SIZE = 10

async def _limpiar_filas_extra(data_rows: int):
    """Limpia filas del sheet más allá de data_rows (que empiezan en row 2)."""
    try:
        from modules.camiones.services.sheets import _col_letter
        ws = sheets_client._worksheet
        if not ws:
            return
        total_ws = await asyncio.to_thread(lambda: ws.row_count)
        if total_ws > data_rows + 1:
            col_fin = _col_letter(10)
            await asyncio.to_thread(
                ws.batch_clear,
                [f"A{data_rows + 2}:{col_fin}{total_ws}"]
            )
            logger.info("Filas extra limpiadas: %d a %d", data_rows + 2, total_ws)
    except Exception as e:
        logger.warning("No se pudieron limpiar filas extra: %s", e)

async def inicializar_sheets_con_local():
    """Sube datos locales a Google Sheets en batches concurrentes."""
    logger.info("Iniciando push a Google Sheets...")
    from modules.camiones.services.sheets import HEADERS_LIST
    camiones = await obtener_todos_camiones()

    # Ordenar por fila_id para mantener correspondencia fila_id ↔ sheet row
    camiones.sort(key=lambda c: c.fila_id)

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
            str(c.estado_servicio or "EN SERVICIO"),
        ])

    # Intentar setAll (1 request)
    result = await sheets_client.set_all_rows(HEADERS_LIST, rows)
    if result.get("success"):
        logger.info("Push completado en 1 request: %d filas.", len(rows))
        await _limpiar_filas_extra(len(rows))
        return

    # Fallback: limpiar filas extra primero, luego actualizar fila por fila
    logger.info("setAll no disponible, limpiando y actualizando filas existentes...")
    await _limpiar_filas_extra(len(rows))
    total = len(rows)
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        tasks = []
        for j, row in enumerate(batch):
            fila = start + j + 2
            tasks.append(sheets_client.update_row(fila, row))
        await asyncio.gather(*tasks)
        logger.info("  Batch %d/%d completado", start // BATCH_SIZE + 1, (total + BATCH_SIZE - 1) // BATCH_SIZE)

    logger.info("Push completado: %d filas actualizadas.", total)

async def push_to_sheets_background():
    """Corre push-to-sheets en un task separado."""
    global _push_task
    try:
        if not sheets_client.enabled:
            logger.error("Push abortado: Google Sheets no está configurado.")
            return
        await inicializar_sheets_con_local()
        logger.info("Push finalizado correctamente.")
    except Exception as e:
        logger.error("Push a Sheets falló: %s", e, exc_info=True)
    finally:
        _push_task = None

async def auto_sync_loop():
    """
    Cada SYNC_INTERVAL segundos: si hay datos locales, hace push a Sheets.
    NO hace pull de Sheets para evitar re-insertar camiones borrados localmente.
    El pull manual se hace con el botón Sync o POST /api/sync.
    """
    global _push_task
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        if not sheets_client.enabled:
            continue
        try:
            n_locales = await obtener_total_camiones_count()
            if n_locales == 0:
                continue
            if _push_task is None or _push_task.done():
                _push_task = asyncio.create_task(push_to_sheets_background())
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Error en auto-sync periódico: %s", e)

async def init_module():
    """Called during app startup"""
    global auto_sync_task
    logger.info("Iniciando módulo Camiones...")
    
    await init_db()
    try:
        poblados = await poblar_ruta_madre_desde_ruta()
        if poblados:
            logger.info("Ruta madre poblada desde ruta para %d camiones", poblados)
    except Exception as e:
        logger.warning("No se pudo poblar ruta_madre (el módulo Rutas se inicializa después): %s", e)
    try:
        asig = await asignar_rutas_desde_madres()
        if asig:
            logger.info("Rutas auto-asignadas a %d camiones desde ruta_madre", asig)
    except Exception as e:
        logger.warning("No se pudo asignar rutas desde madres: %s", e)
    
    total_locales = await obtener_total_camiones_count()
    await sheets_client.initialize()
    
    # Si no hay datos locales, seed desde Excel (con o sin sheets)
    if total_locales == 0:
        excel_path = settings.bootstrap_excel
        if not os.path.exists(excel_path):
            excel_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", excel_path)
        if os.path.exists(excel_path):
            logger.info("BD vacía. Importando desde Excel: %s", excel_path)
            records = parse_excel_camiones(excel_path)
            if records:
                await guardar_camiones_bulk(records)
                total_locales = len(records)
                logger.info("Importación desde Excel: %d registros", total_locales)
        else:
            logger.warning("Excel no encontrado: %s", excel_path)
    
    if sheets_client.enabled:
        try:
            sheet_result = await sheets_client.read_all_rows()
            sheet_has_data = sheet_result.get("success") and len(sheet_result.get("data", [])) > 0
            
            if total_locales == 0 and sheet_has_data:
                n_sheet = len(sheet_result["data"])
                logger.info("Local vacío, sheets con %d registros. Sync sheets -> local.", n_sheet)
                await sincronizar_desde_sheets()
                total_locales = n_sheet
            
            if total_locales > 0 and sheet_has_data:
                n_sheet = len(sheet_result["data"])
                if total_locales < n_sheet:
                    logger.info("Sheet tiene %d registros vs local %d. Sync sheets -> local.", n_sheet, total_locales)
                    await sincronizar_desde_sheets()
                    total_locales = n_sheet
            
            if total_locales > 0 and (not sheet_has_data or total_locales > len(sheet_result.get("data", []))):
                logger.info("Local (%d) > sheets (%d). Push en 2do plano.", total_locales,
                            len(sheet_result.get("data", [])) if sheet_has_data else 0)
                asyncio.create_task(push_to_sheets_background())
        except Exception as e:
            logger.warning("Sync/push inicial falló (no crítico): %s", e)
    
    await update_queue.start()
    logger.info("Módulo Camiones listo (auto-sync desactivado, solo manual).")

async def shutdown_module():
    """Called during app shutdown"""
    await update_queue.stop()
    logger.info("Módulo Camiones detenido.")
