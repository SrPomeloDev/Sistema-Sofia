"""
routes.py — API REST endpoints para el módulo Camiones.
"""

import logging
import json
import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from fastapi import APIRouter, HTTPException, status

from modules.camiones.config import settings
from modules.camiones.models import (
    CamionCreate,
    CamionUpdate,
    CamionResponse,
    UpdateSheetResponse,
    AuditEntry,
    SyncStatusResponse,
    FletePromedioResponse
)
from modules.camiones.db.database import (
    init_db,
    crear_registro_auditoria,
    actualizar_estado_auditoria,
    obtener_historial,
    obtener_todos_camiones,
    obtener_camion_por_placa,
    obtener_camion_por_fila,
    guardar_camiones_bulk,
    upsert_camiones_desde_sheets,
    crear_camion_local,
    actualizar_camion_local,
    eliminar_camion_local,
    obtener_siguiente_nro_sucursal,
    obtener_max_fila_id,
    obtener_pendientes_sincronizacion_count,
    obtener_total_camiones_count,
    obtener_ultimo_cambio,
    obtener_camiones_por_sucursal,
    obtener_promedio_flete_por_sucursal
)
from modules.camiones.services.sheets import sheets_client
from modules.camiones.services.queue import UpdateQueue, QueueItem
from modules.camiones.services.excel_parser import parse_excel_camiones
from modules.camiones.services.bootstrap import bootstrap_sheets

logger = logging.getLogger(__name__)

# Cabeceras por defecto para Google Sheets
HEADERS = [
    "Nº",
    "Nº placa ",
    "Estado de trabajo",
    "Tipo de combustible",
    "Costo flete (Bs/viaje)",
    "Sucursal",
    "Capacidad en KG",
    "Capacidad de carga útil en maples",
    "Capacidad de carga útil en Kg",
    "Sistema Camión"
]

# ── Callback para el worker de la cola ─────────────────────────────────
async def write_callback(item: QueueItem):
    """
    Ejecuta la escritura real en Google Sheets (vía Apps Script o gspread).
    """
    from modules.camiones.db.database import marcar_sincronizado
    
    if not sheets_client.enabled:
        logger.warning("Se omitió el envío a Google Sheets para el item #%s porque el cliente no está habilitado.", item.auditoria_id)
        return

    if item.action == "append":
        result = await sheets_client.append_row(item.valores)
        if result.get("success"):
            fila_real = result.get("data", {}).get("fila_insertada") or result.get("data")
            await marcar_sincronizado(fila_id=item.fila_id, nuevo_fila_id_real=fila_real)
        else:
            raise Exception(result.get("error", "Error desconocido al hacer append"))
    elif item.action == "update_row":
        result = await sheets_client.update_row(item.fila_id, item.valores)
        if result.get("success"):
            await marcar_sincronizado(fila_id=item.fila_id)
        else:
            raise Exception(result.get("error", "Error desconocido al hacer update"))

    await actualizar_estado_auditoria(auditoria_id=item.auditoria_id, estado="éxito")

# Cola asíncrona
update_queue = UpdateQueue(
    write_callback=write_callback,
    max_retries=settings.max_retries,
    retry_base_delay=settings.retry_base_delay,
    rate_limit_max=settings.rate_limit_max,
    rate_limit_window=settings.rate_limit_window,
)

router = APIRouter(tags=["Camiones"])

# ── Endpoints API ──────────────────────────────────────────────────────

@router.post("/api/push-to-sheets")
async def push_to_sheets():
    """
    Sube TODOS los datos locales (SQLite) al Google Sheet en background.
    """
    if not sheets_client.enabled:
        raise HTTPException(400, "Google Sheets no está configurado")
    from modules.camiones.lifecycle import _push_task, push_to_sheets_background
    if _push_task and not _push_task.done():
        return {"success": True, "message": "Ya hay una subida en progreso."}
    _push_task = asyncio.create_task(push_to_sheets_background())
    return {"success": True, "message": "Subida iniciada en segundo plano. Esperá unos minutos y revisá el Sheet."}

@router.get("/api/health")
async def health():
    """Health check simple para monitoreo."""
    return {"status": "ok", "mode": "sheets" if sheets_client.enabled else "local"}

@router.get("/api/status", response_model=SyncStatusResponse)
async def get_status():
    """
    Obtiene el estado de la conexión a Sheets y la cola de procesamiento.
    """
    pendientes = await obtener_pendientes_sincronizacion_count()
    total = await obtener_total_camiones_count()
    ultimo_cambio, ultimo_por, ultimo_email = await obtener_ultimo_cambio()
    por_sucursal = await obtener_camiones_por_sucursal()
    
    return SyncStatusResponse(
        modo="sheets" if sheets_client.enabled else "local",
        sheets_configuradas=sheets_client.enabled,
        pendientes_sincronizacion=pendientes,
        total_registros=total,
        ultimo_cambio=ultimo_cambio,
        ultimo_cambio_por=ultimo_por,
        ultimo_cambio_email=ultimo_email,
        camiones_por_sucursal=por_sucursal
    )

@router.get("/api/camiones", response_model=list[CamionResponse])
async def list_camiones():
    """
    Lista todos los camiones desde la caché de SQLite (rápido).
    """
    try:
        return await obtener_todos_camiones()
    except Exception as e:
        logger.error("Error al listar camiones: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/camiones/export/xlsx")
async def export_camiones_xlsx(
    placa: str = "",
    sucursal: str = "",
    tipo_combustible: str = "",
    sistema_camion: str = "",
    estado_servicio: str = ""
):
    """
    Exporta camiones a Excel (.xlsx) aplicando los mismos filtros del dashboard.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from io import BytesIO

    todos = await obtener_todos_camiones()
    query = placa.strip().lower()
    camiones = [
        c for c in todos
        if (not query or query in c.placa.lower())
        and (not sucursal or c.sucursal == sucursal)
        and (not tipo_combustible or c.tipo_combustible == tipo_combustible)
        and (not sistema_camion or c.sistema_camion == sistema_camion)
        and (not estado_servicio or (c.estado_servicio or "EN SERVICIO") == estado_servicio)
    ]
    wb = Workbook()
    ws = wb.active
    ws.title = "Camiones"

    headers = ["Nº","Placa","Sucursal","Sistema","Servicio","Estado Trabajo",
               "Combustible","Flete (Bs)","Cap. KG","Maples","Cap. Útil Kg","F. 0.75"]

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    data_font = Font(name="Calibri", size=10)
    for i, c in enumerate(camiones, 2):
        vals = [
            i - 1, c.placa, c.sucursal, c.sistema_camion or "SIN INFORMACIÓN",
            c.estado_servicio or "EN SERVICIO", c.estado_trabajo,
            c.tipo_combustible, c.costo_flete or 0,
            c.capacidad_kg or 0, c.capacidad_maples or 0, c.capacidad_util_kg or 0,
            round((c.capacidad_maples or 0) * 0.75, 2),
        ]
        for col, v in enumerate(vals, 1):
            cell = ws.cell(row=i, column=col, value=v)
            cell.font = data_font
            cell.border = thin_border

    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 16
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 14
    ws.column_dimensions["G"].width = 16
    ws.column_dimensions["H"].width = 12
    ws.column_dimensions["I"].width = 10
    ws.column_dimensions["J"].width = 10
    ws.column_dimensions["K"].width = 12
    ws.column_dimensions["L"].width = 10

    from fastapi.responses import StreamingResponse
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=camiones_{datetime.now(timezone.utc).strftime('%Y%m%d')}.xlsx"}
    )

@router.post("/api/camiones", response_model=UpdateSheetResponse)
async def create_camion(request: CamionCreate):
    """
    Registra un nuevo camión.
    Calcula el Nº según la sucursal y la fila_id según el max local.
    Sincroniza en background si Sheets está habilitado.
    """
    logger.info("Registrando nuevo camión con placa: %s", request.placa)
    
    # Verificar placa duplicada
    duplicado = await obtener_camion_por_placa(request.placa)
    if duplicado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La placa '{request.placa}' ya se encuentra registrada."
        )
        
    try:
        # 1. Auto-calcular correlativo Nº por sucursal
        siguiente_nro = await obtener_siguiente_nro_sucursal(request.sucursal)
        
        # 2. Auto-calcular capacidad útil en Kg si no se especificó o para consistencia (factor 1.95)
        capacidad_util_calculada = round(request.capacidad_maples * 1.95, 2)
        
        # 3. Auto-calcular el fila_id
        max_fila = await obtener_max_fila_id()
        nueva_fila = max_fila + 1
        
        camion_dict = request.model_dump()
        camion_dict["nro"] = str(siguiente_nro)
        camion_dict["capacidad_util_kg"] = capacidad_util_calculada
        
        # Estado inicial
        estado_sinc = "pendiente_insercion" if sheets_client.enabled else "local"
        
        # Guardar localmente de inmediato
        await crear_camion_local(camion_dict, nueva_fila, estado_sinc)
        
        auditoria_id = None
        # Si Sheets está habilitado, encolar escritura
        if sheets_client.enabled:
            valores_fila = [
                str(siguiente_nro),
                request.placa,
                request.estado_trabajo,
                request.tipo_combustible,
                str(request.costo_flete),
                request.sucursal,
                str(request.capacidad_kg),
                str(request.capacidad_maples),
                str(capacidad_util_calculada),
                request.sistema_camion
            ]
            
            # Registrar auditoría
            auditoria_id = await crear_registro_auditoria(
                fila_id=nueva_fila,
                accion="crear",
                valores=json.dumps(camion_dict)
            )
            
            # Encolar
            item = QueueItem(
                auditoria_id=auditoria_id,
                action="append",
                fila_id=nueva_fila,
                valores=valores_fila
            )
            await update_queue.enqueue(item)
            
            return UpdateSheetResponse(
                success=True,
                message=f"Registro guardado localmente y encolado para Google Sheets (auditoría #{auditoria_id}).",
                auditoria_id=auditoria_id
            )
        else:
            return UpdateSheetResponse(
                success=True,
                message="Registro guardado localmente de forma exitosa (Modo Local).",
                auditoria_id=None
            )
            
    except Exception as e:
        logger.error("Error al registrar camión: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/api/camiones/{fila_id}", response_model=UpdateSheetResponse)
async def update_camion(fila_id: int, request: CamionUpdate):
    """
    Modifica los detalles de un camión existente.
    Sincroniza en background si Sheets está habilitado.
    """
    logger.info("Modificando camión de la fila_id: %d", fila_id)
    
    camion_existente = await obtener_camion_por_fila(fila_id)
    if not camion_existente:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Camión en la fila {fila_id} no encontrado."
        )
        
    try:
        camion_dict = request.model_dump(exclude_unset=True)
        
        # Si se modificaron los maples, recalcular capacidad útil
        if "capacidad_maples" in camion_dict:
            camion_dict["capacidad_util_kg"] = round(camion_dict["capacidad_maples"] * 1.95, 2)
            
        estado_sinc = "pendiente_actualizacion" if sheets_client.enabled else "local"
        
        # Guardar en base local
        camion_actualizado = await actualizar_camion_local(fila_id, camion_dict, estado_sinc)
        
        auditoria_id = None
        if sheets_client.enabled and camion_actualizado:
            # Lista completa ordenada de columnas A-J
            valores_fila = [
                str(camion_actualizado.nro or ""),
                str(camion_actualizado.placa),
                str(camion_actualizado.estado_trabajo),
                str(camion_actualizado.tipo_combustible),
                str(camion_actualizado.costo_flete),
                str(camion_actualizado.sucursal),
                str(camion_actualizado.capacidad_kg),
                str(camion_actualizado.capacidad_maples),
                str(camion_actualizado.capacidad_util_kg),
                str(camion_actualizado.sistema_camion)
            ]
            
            # Registrar auditoría
            auditoria_id = await crear_registro_auditoria(
                fila_id=fila_id,
                accion="editar",
                valores=json.dumps(camion_dict)
            )
            
            # Encolar
            item = QueueItem(
                auditoria_id=auditoria_id,
                action="update_row",
                fila_id=fila_id,
                valores=valores_fila
            )
            await update_queue.enqueue(item)
            
            return UpdateSheetResponse(
                success=True,
                message=f"Modificación guardada localmente y encolada para Google Sheets (auditoría #{auditoria_id}).",
                auditoria_id=auditoria_id
            )
        else:
            return UpdateSheetResponse(
                success=True,
                message="Modificación guardada localmente de forma exitosa (Modo Local).",
                auditoria_id=None
            )
            
    except Exception as e:
        logger.error("Error al actualizar camión: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/api/camiones/{fila_id}", response_model=UpdateSheetResponse)
async def delete_camion(fila_id: int):
    """
    Elimina un camión de SQLite y lo encola para borrar de Sheets.
    """
    logger.info("Eliminando camión fila_id: %d", fila_id)
    
    camion = await obtener_camion_por_fila(fila_id)
    if not camion:
        raise HTTPException(status_code=404, detail="Camión no encontrado.")
    
    try:
        if sheets_client.enabled:
            result = await sheets_client.delete_row(fila_id)
            if not result.get("success"):
                logger.error("Delete en Sheets falló: %s", result.get("error"))
                return UpdateSheetResponse(
                    success=False,
                    message=f"No se pudo eliminar en Google Sheets: {result.get('error', 'error desconocido')}",
                    auditoria_id=None
                )
            # Ajustar fila_id local para los registros que estaban debajo
            from modules.camiones.db.database import CamionDb, async_session_factory
            async with async_session_factory() as session:
                stmt = select(CamionDb).where(CamionDb.fila_id > fila_id).order_by(CamionDb.fila_id)
                rows_to_shift = await session.execute(stmt)
                for row in rows_to_shift.scalars():
                    row.fila_id -= 1
                await session.commit()
        
        await eliminar_camion_local(fila_id)
        
        auditoria_id = None
        if sheets_client.enabled:
            auditoria_id = await crear_registro_auditoria(
                fila_id=fila_id, accion="eliminar",
                valores=json.dumps({"placa": camion.placa, "eliminado_por": ""})
            )
        
        return UpdateSheetResponse(
            success=True,
            message=f"Camión {camion.placa} eliminado correctamente.",
            auditoria_id=auditoria_id
        )
    except Exception as e:
        logger.error("Error al eliminar camión: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/sync")
async def force_sync():
    """
    Forzar sincronización desde Google Sheets usando UPSERT.
    Así los camiones agregados localmente no se pierden.
    """
    if not sheets_client.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Sheets no está configurado o está deshabilitado."
        )

    try:
        result = await sheets_client.read_all_rows()
        if not result.get("success"):
            return {"success": False, "message": result.get("error", "Error del Apps Script")}

        rows = result.get("data", [])
        if not rows:
            return {"success": False, "message": "No hay datos en el Sheet."}

        camiones = []
        for obj in rows:
            camiones.append({
                "fila_id": obj.get("fila_id", 0),
                "nro": str(obj.get("nro", "")),
                "placa": str(obj.get("placa", "")),
                "estado_trabajo": str(obj.get("estado_trabajo", "Fijo")),
                "tipo_combustible": str(obj.get("tipo_combustible", "GAS-GASOLINA")),
                "costo_flete": float(obj.get("costo_flete", 0)),
                "sucursal": str(obj.get("sucursal", "")),
                "capacidad_kg": int(obj.get("capacidad_kg", 0)),
                "capacidad_maples": int(obj.get("capacidad_maples", 0)),
                "capacidad_util_kg": float(obj.get("capacidad_util_kg", 0)),
            })

        # Add sistema_camion from existing local records if not in Sheets data
        camiones_local = {c.placa: c for c in await obtener_todos_camiones()}
        for c in camiones:
            if c["placa"] in camiones_local and hasattr(camiones_local[c["placa"]], "sistema_camion"):
                c["sistema_camion"] = camiones_local[c["placa"]].sistema_camion
            else:
                c["sistema_camion"] = "SIN INFORMACIÓN"

        await upsert_camiones_desde_sheets(camiones)
        return {"success": True, "message": f"Sincronizados/actualizados {len(camiones)} camiones."}
    except Exception as e:
        logger.error("Error en sincronización forzada: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/fletes", response_model=list[FletePromedioResponse])
async def list_fletes():
    """
    Obtiene el promedio de flete por sucursal.
    """
    try:
        data = await obtener_promedio_flete_por_sucursal()
        return [FletePromedioResponse(**d) for d in data]
    except Exception as e:
        logger.error("Error al obtener fletes: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/bootstrap")
async def run_bootstrap():
    """
    Lee los 3 archivos HTML (LISTA CAMIONES 2024.html, DB.html, Hoja1.html),
    los mergea sin duplicados ni ruteos, y escribe en Google Sheets.
    """
    try:
        result = await bootstrap_sheets(force_write=True)
        return {
            "success": True,
            "total": len(result),
            "message": f"Bootstrap completado: {len(result)} camiones escritos en Sheets."
        }
    except Exception as e:
        logger.error("Error en bootstrap: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/auditoria", response_model=list[AuditEntry])
async def list_auditoria(limit: int = 20):
    """
    Obtiene los registros de auditoría recientes.
    """
    try:
        registros = await obtener_historial(limit=limit)
        
        response_list = []
        for r in registros:
            # Formatear fecha
            creado_str = r.creado_en.strftime("%d/%m/%Y %H:%M:%S")
            response_list.append(
                AuditEntry(
                    id=r.id,
                    fila_id=r.fila_id,
                    accion=r.accion,
                    valores=r.valores,
                    estado=r.estado,
                    error=r.error,
                    creado_en=creado_str
                )
            )
        return response_list
    except Exception as e:
        logger.error("Error al listar auditoría: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

