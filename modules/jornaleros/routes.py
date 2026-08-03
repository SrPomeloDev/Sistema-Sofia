"""
routes.py — Endpoints REST del módulo Jornaleros.

Todos los endpoints mutantes requieren `?token=` válido (misma auth que
camiones/rutas). Las lecturas son públicas.
"""

import asyncio
import logging
from io import BytesIO
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from modules.camiones.auth import verify_session
from modules.jornaleros.models import (
    JornaleroCreate, JornaleroUpdate, JornaleroResponse,
    JornaleroListResponse, OperationResponse,
)
from modules.jornaleros.db.database import (
    get_all_jornaleros, get_jornalero_by_id, create_jornalero,
    update_jornalero, delete_jornalero, seed_desde_excel, limpiar_todo,
    obtener_stats, upsert_from_sheet_rows, obtener_todos, marcar_sincronizado,
)
from modules.jornaleros.sheets import jornaleros_sheets_client, HEADERS_LIST

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Jornaleros"])

_push_task: asyncio.Task | None = None


def _require_auth(token: str):
    session = verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return session


def _a_response(row) -> JornaleroResponse:
    return JornaleroResponse(
        id=row.id,
        fecha_inicial=row.fecha_inicial,
        fecha_final=row.fecha_final,
        tipo_trabajador=row.tipo_trabajador,
        cd=row.cd,
        unidad=row.unidad,
        area=row.area,
        cantidad_jornaleros=row.cantidad_jornaleros,
        horas_trabajadas=row.horas_trabajadas,
        dias_trabajados_totales=row.dias_trabajados_totales,
        dias_trabajados_laborales=row.dias_trabajados_laborales,
        llenado_por=row.llenado_por,
        fecha_creacion=row.fecha_creacion,
        estado_sincronizacion=row.estado_sincronizacion,
        error_sincronizacion=row.error_sincronizacion,
    )


def _fecha_param(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", ""))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Fecha inválida: {val}. Usá formato ISO (YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS)")


@router.get("/api/jornaleros", response_model=JornaleroListResponse)
async def listar_jornaleros(
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    cd: str | None = None,
    area: str | None = None,
    tipo_trabajador: str | None = None,
    llenado_por: str | None = None,
    fecha_inicial__gte: str | None = None,
    fecha_inicial__lte: str | None = None,
    fecha_final__gte: str | None = None,
    fecha_final__lte: str | None = None,
):
    try:
        filas, total = await get_all_jornaleros(
            offset=offset, limit=limit, cd=cd, area=area,
            tipo_trabajador=tipo_trabajador, llenado_por=llenado_por,
            fecha_inicial_gte=_fecha_param(fecha_inicial__gte),
            fecha_inicial_lte=_fecha_param(fecha_inicial__lte),
            fecha_final_gte=_fecha_param(fecha_final__gte),
            fecha_final_lte=_fecha_param(fecha_final__lte),
        )
        return JornaleroListResponse(
            success=True,
            data=[_a_response(r) for r in filas],
            total=total, offset=offset, limit=limit,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al listar jornaleros: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jornaleros", response_model=OperationResponse)
async def crear_jornalero(body: JornaleroCreate, token: str = Query("")):
    _require_auth(token)
    try:
        row = await create_jornalero(body.model_dump())
        return OperationResponse(success=True, message="Registro de jornalero creado (pendiente de sincronizar)", data=_a_response(row))
    except Exception as e:
        logger.error("Error al crear jornalero: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/jornaleros/{jornalero_id}", response_model=OperationResponse)
async def actualizar_jornalero(jornalero_id: str, body: JornaleroUpdate, token: str = Query("")):
    _require_auth(token)
    try:
        datos = body.model_dump(exclude_unset=True)
        if not datos:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar")
        row = await update_jornalero(jornalero_id, datos)
        if not row:
            raise HTTPException(status_code=404, detail="Registro de jornalero no encontrado")
        return OperationResponse(success=True, message="Registro actualizado (pendiente de sincronizar)", data=_a_response(row))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al actualizar jornalero %s: %s", jornalero_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/jornaleros/{jornalero_id}", response_model=OperationResponse)
async def eliminar_jornalero(jornalero_id: str, token: str = Query("")):
    _require_auth(token)
    try:
        # Si sheets está configurado, intenta borrar la fila remota (best effort)
        if jornaleros_sheets_client.enabled:
            await jornaleros_sheets_client.delete_by_id(jornalero_id)
        ok = await delete_jornalero(jornalero_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Registro de jornalero no encontrado")
        return OperationResponse(success=True, message="Registro eliminado")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al eliminar jornalero %s: %s", jornalero_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jornaleros/sync")
async def sync_desde_sheets(token: str = Query("")):
    """Pull: trae todos los registros de Google Sheets y los upserta en la BD."""
    _require_auth(token)
    if not jornaleros_sheets_client.enabled:
        raise HTTPException(status_code=400, detail="Google Sheets no está configurado para jornaleros")
    try:
        await jornaleros_sheets_client.initialize()
        result = await jornaleros_sheets_client.read_all_rows()
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Error al leer de Sheets"))
        datos = result.get("data") or []
        if datos and _es_fila_encabezados(datos[0]):
            resumen = await upsert_from_sheet_rows(datos)
        else:
            resumen = {"creados": 0, "actualizados": 0, "omitidos": len(datos)}
        return {"success": True, "message": "Sincronización completada", "detalles": resumen}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error en sync de jornaleros: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


def _es_fila_encabezados(fila: list) -> bool:
    return any(str(c).strip().upper() == "ID" for c in fila) and any(str(c).strip().upper() == "CD" for c in fila)


def _fila_a_lista(row) -> list:
    """Convierte un registro de BD a la lista de 13 valores del sheet."""
    def _fmt_dt(val: datetime) -> str:
        return val.strftime("%Y-%m-%d") if val else ""
    return [
        row.id,
        _fmt_dt(row.fecha_inicial),
        _fmt_dt(row.fecha_final),
        row.tipo_trabajador or "JORNALERO",
        row.cd,
        row.unidad or "",
        row.area or "",
        row.cantidad_jornaleros or 0,
        row.horas_trabajadas or 0,
        row.dias_trabajados_totales or 0,
        row.dias_trabajados_laborales or 0,
        row.llenado_por or "",
        _fmt_dt(row.fecha_creacion),
    ]


async def _push_task_body():
    registros = await obtener_todos()
    ok = 0
    fallidos = 0
    for row in registros:
        valores = _fila_a_lista(row)
        result = await jornaleros_sheets_client.upsert_row(row.id, valores)
        if result.get("success"):
            await marcar_sincronizado(row.id)
            ok += 1
        else:
            await marcar_sincronizado(row.id, error=result.get("error", "Error desconocido"))
            fallidos += 1
    return {"total": len(registros), "sincronizados": ok, "fallidos": fallidos}


@router.post("/api/jornaleros/push-to-sheets")
async def push_a_sheets(token: str = Query("")):
    """Push: envía los registros pendientes a Google Sheets en segundo plano."""
    _require_auth(token)
    global _push_task
    if not jornaleros_sheets_client.enabled:
        raise HTTPException(status_code=400, detail="Google Sheets no está configurado para jornaleros")
    if _push_task and not _push_task.done():
        return {"success": True, "running": True, "message": "Ya hay un push en progreso."}
    await jornaleros_sheets_client.initialize()
    await jornaleros_sheets_client.write_headers()
    _push_task = asyncio.create_task(_push_task_body())
    return {"success": True, "running": True, "message": "Push iniciado en segundo plano."}


@router.get("/api/jornaleros/push-status")
async def push_status():
    global _push_task
    if _push_task and not _push_task.done():
        return {"success": True, "running": True, "message": "Push en progreso..."}
    if _push_task and _push_task.done() and _push_task.exception():
        return {"success": False, "running": False, "message": f"Push falló: {_push_task.exception()}"}
    return {"success": True, "running": False, "message": "Sin push activo."}


@router.get("/api/jornaleros/stats")
async def stats_jornaleros():
    try:
        return await obtener_stats()
    except Exception as e:
        logger.error("Error en stats de jornaleros: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jornaleros/export/xlsx")
async def export_jornaleros_xlsx(
    token: str = Query(""),
    cd: str | None = None,
    area: str | None = None,
    fecha_inicial__gte: str | None = None,
    fecha_final__lte: str | None = None,
):
    """Exporta jornaleros filtrados a Excel (.xlsx). Requiere token."""
    _require_auth(token)
    try:
        filas, _ = await get_all_jornaleros(
            offset=0, limit=500, cd=cd, area=area,
            fecha_inicial_gte=_fecha_param(fecha_inicial__gte),
            fecha_final_lte=_fecha_param(fecha_final__lte),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error en export jornaleros: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "Jornaleros"

    headers = ["ID", "Fecha Inicial", "Fecha Final", "Tipo Trabajador", "CD", "Unidad",
               "Área", "Cant. Jornaleros", "Horas Trabajadas", "Días Totales",
               "Días Laborales", "Llenado por", "Fecha Creación", "Estado Sync"]

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

    for i, r in enumerate(filas, 2):
        valores = [
            r.id, r.fecha_inicial.strftime("%Y-%m-%d"), r.fecha_final.strftime("%Y-%m-%d"),
            r.tipo_trabajador, r.cd, r.unidad, r.area,
            r.cantidad_jornaleros, r.horas_trabajadas, r.dias_trabajados_totales,
            r.dias_trabajados_laborales, r.llenado_por,
            r.fecha_creacion.strftime("%Y-%m-%d %H:%M") if r.fecha_creacion else "",
            r.estado_sincronizacion,
        ]
        for col, val in enumerate(valores, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    widths = [12, 14, 14, 16, 14, 26, 12, 14, 14, 12, 12, 14, 18, 14]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = w

    ws.freeze_panes = "A2"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=jornaleros.xlsx"},
    )


@router.post("/api/jornaleros/seed")
async def seed_jornaleros(token: str = Query(""), confirm: bool = Query(False)):
    """Importa la hoja Horas_Jornaleros de DB_PROD_GDN.xlsx a la BD."""
    _require_auth(token)
    if not confirm:
        raise HTTPException(status_code=400, detail="Debe enviar ?confirm=true para ejecutar el seed")
    try:
        resultado = await seed_desde_excel()
        return {"success": True, "message": f"Seed completado: {resultado['creados']} creados, {resultado['actualizados']} actualizados, {resultado['omitidos']} omitidos"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en seed de jornaleros: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/jornaleros/{jornalero_id}", response_model=OperationResponse)
async def obtener_jornalero(jornalero_id: str):
    try:
        row = await get_jornalero_by_id(jornalero_id)
        if not row:
            raise HTTPException(status_code=404, detail="Registro de jornalero no encontrado")
        return OperationResponse(success=True, message="OK", data=_a_response(row))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al obtener jornalero %s: %s", jornalero_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/jornaleros/reseed")
async def reseed_jornaleros(token: str = Query(""), confirm: bool = Query(False)):
    """Limpia la tabla y re-importa desde el Excel."""
    _require_auth(token)
    if not confirm:
        raise HTTPException(status_code=400, detail="Debe enviar ?confirm=true para ejecutar el re-seed")
    try:
        await limpiar_todo()
        resultado = await seed_desde_excel()
        return {"success": True, "message": f"Re-seed completado: {resultado['creados']} creados, {resultado['actualizados']} actualizados"}
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en reseed de jornaleros: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
