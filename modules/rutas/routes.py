import logging
import os
from fastapi import APIRouter, HTTPException, status, Query
from sqlalchemy.exc import IntegrityError

from modules.camiones.auth import verify_session
from modules.rutas.models import (
    RutaMadreCreate, RutaMadreUpdate, RutaMadreConHijasResponse,
    RutaHijaCreate, RutaHijaUpdate, RutaHijaResponse,
    OperationResponse,
)
from modules.rutas.db.database import (
    RutaMadreDb, RutaHijaDb,
    obtener_madres_con_hijas, obtener_madre_por_id,
    crear_madre, actualizar_madre, eliminar_madre,
    crear_hija, actualizar_hija, eliminar_hija,
    seed_desde_excel, limpiar_todo,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Rutas"])


def _require_auth(token: str):
    session = verify_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return session


def madre_a_response(m: RutaMadreDb) -> RutaMadreConHijasResponse:
    return RutaMadreConHijasResponse(
        id=m.id,
        sucursal=m.sucursal,
        nombre=m.nombre,
        hijas=[RutaHijaResponse(
            id=h.id, ruta_madre_id=h.ruta_madre_id,
            ruta_hija=h.ruta_hija, flete=h.flete, metodo=h.metodo
        ) for h in m.hijas],
    )


@router.get("/api/rutas/madres")
async def listar_madres(sucursal: str | None = None):
    try:
        madres = await obtener_madres_con_hijas(sucursal)
        return [madre_a_response(m) for m in madres]
    except Exception as e:
        logger.error("Error al listar madres: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/rutas/madres/{madre_id}")
async def obtener_madre(madre_id: int):
    try:
        madre = await obtener_madre_por_id(madre_id)
        if not madre:
            raise HTTPException(status_code=404, detail="Ruta madre no encontrada")
        return madre_a_response(madre)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al obtener madre %d: %s", madre_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rutas/madres", response_model=OperationResponse)
async def crear_ruta_madre(body: RutaMadreCreate, token: str = Query("")):
    _require_auth(token)
    try:
        madre = await crear_madre(body.sucursal, body.nombre)
        return OperationResponse(success=True, message="Ruta madre creada", data=madre_a_response(madre))
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"Ya existe una ruta madre '{body.nombre}' en sucursal '{body.sucursal}'")
    except Exception as e:
        logger.error("Error al crear madre: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/rutas/madres/{madre_id}", response_model=OperationResponse)
async def actualizar_ruta_madre(madre_id: int, body: RutaMadreUpdate, token: str = Query("")):
    _require_auth(token)
    try:
        datos = body.model_dump(exclude_unset=True)
        if not datos:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar")
        madre = await actualizar_madre(madre_id, datos)
        if not madre:
            raise HTTPException(status_code=404, detail="Ruta madre no encontrada")
        return OperationResponse(success=True, message="Ruta madre actualizada", data=madre_a_response(madre))
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Conflicto: ya existe otra ruta madre con esos valores")
    except Exception as e:
        logger.error("Error al actualizar madre %d: %s", madre_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/rutas/madres/{madre_id}", response_model=OperationResponse)
async def eliminar_ruta_madre(madre_id: int, token: str = Query("")):
    _require_auth(token)
    try:
        ok = await eliminar_madre(madre_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Ruta madre no encontrada")
        return OperationResponse(success=True, message="Ruta madre eliminada")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al eliminar madre %d: %s", madre_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rutas/hijas", response_model=OperationResponse)
async def crear_ruta_hija(body: RutaHijaCreate, token: str = Query("")):
    _require_auth(token)
    try:
        hija = await crear_hija(body.ruta_madre_id, body.ruta_hija, body.flete, body.metodo)
        return OperationResponse(
            success=True, message="Ruta hija creada",
            data=RutaHijaResponse(id=hija.id, ruta_madre_id=hija.ruta_madre_id,
                                  ruta_hija=hija.ruta_hija, flete=hija.flete, metodo=hija.metodo)
        )
    except IntegrityError:
        raise HTTPException(status_code=400, detail="La ruta madre especificada no existe")
    except Exception as e:
        logger.error("Error al crear hija: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/rutas/hijas/{hija_id}", response_model=OperationResponse)
async def actualizar_ruta_hija(hija_id: int, body: RutaHijaUpdate, token: str = Query("")):
    _require_auth(token)
    try:
        datos = body.model_dump(exclude_unset=True)
        if not datos:
            raise HTTPException(status_code=400, detail="No hay campos para actualizar")
        hija = await actualizar_hija(hija_id, datos)
        if not hija:
            raise HTTPException(status_code=404, detail="Ruta hija no encontrada")
        return OperationResponse(
            success=True, message="Ruta hija actualizada",
            data=RutaHijaResponse(id=hija.id, ruta_madre_id=hija.ruta_madre_id,
                                  ruta_hija=hija.ruta_hija, flete=hija.flete, metodo=hija.metodo)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al actualizar hija %d: %s", hija_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/rutas/hijas/{hija_id}", response_model=OperationResponse)
async def eliminar_ruta_hija(hija_id: int, token: str = Query("")):
    _require_auth(token)
    try:
        ok = await eliminar_hija(hija_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Ruta hija no encontrada")
        return OperationResponse(success=True, message="Ruta hija eliminada")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error al eliminar hija %d: %s", hija_id, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rutas/seed", response_model=OperationResponse)
async def seed_rutas(token: str = Query(""), confirm: bool = Query(False)):
    _require_auth(token)
    if not confirm:
        raise HTTPException(status_code=400, detail="Debe enviar ?confirm=true para ejecutar el seed")
    try:
        resultado = await seed_desde_excel()
        return OperationResponse(
            success=True,
            message=f"Seed completado: {resultado['madres']} rutas madre, {resultado['hijas']} rutas hijas",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en seed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/rutas/reseed", response_model=OperationResponse)
async def reseed_rutas(token: str = Query(""), confirm: bool = Query(False)):
    _require_auth(token)
    if not confirm:
        raise HTTPException(status_code=400, detail="Debe enviar ?confirm=true para ejecutar el re-seed")
    try:
        await limpiar_todo()
        resultado = await seed_desde_excel()
        return OperationResponse(
            success=True,
            message=f"Re-seed completado: {resultado['madres']} madres, {resultado['hijas']} hijas",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error en reseed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
