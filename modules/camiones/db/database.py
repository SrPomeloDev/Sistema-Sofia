"""
database.py — Inicialización de SQLite y operaciones CRUD para camiones y auditoría.
"""

import logging
from datetime import datetime, timezone
import json

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String, Text, DateTime, Float, select, func, delete

from modules.camiones.config import settings

logger = logging.getLogger(__name__)

# Engine y sesión asíncrona
engine = create_async_engine(settings.database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class CamionDb(Base):
    """
    Tabla de camiones sincronizada localmente.
    """
    __tablename__ = "camiones"

    fila_id: Mapped[int] = mapped_column(Integer, primary_key=True) # Fila en Google Sheets (2, 3, 4...)
    nro: Mapped[str | None] = mapped_column(String(50), nullable=True) # Nº secuencial por sucursal
    placa: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    estado_trabajo: Mapped[str] = mapped_column(String(50), default="Fijo")
    ruta: Mapped[str] = mapped_column(String(50), default="local")
    tipo_combustible: Mapped[str] = mapped_column(String(50), default="GAS-GASOLINA")
    costo_flete: Mapped[float] = mapped_column(Float, default=0.0)
    sucursal: Mapped[str] = mapped_column(String(100), nullable=False)
    capacidad_kg: Mapped[int] = mapped_column(Integer, default=0)
    capacidad_maples: Mapped[int] = mapped_column(Integer, default=0)
    capacidad_util_kg: Mapped[float] = mapped_column(Float, default=0.0)
    sistema_camion: Mapped[str] = mapped_column(String(50), default="SIN INFORMACIÓN")
    estado_servicio: Mapped[str] = mapped_column(String(20), default="EN SERVICIO")
    propietario: Mapped[str] = mapped_column(String(200), default="")
    modificado_por: Mapped[str] = mapped_column(String(100), default="")
    modificado_por_email: Mapped[str] = mapped_column(String(100), default="")
    
    @property
    def factor_0_75(self) -> float:
        return round((self.capacidad_maples or 0) * 0.75, 2)

    # Control de sincronización
    estado_sincronizacion: Mapped[str] = mapped_column(String(50), default="sincronizado") # 'sincronizado', 'pendiente_insercion', 'pendiente_actualizacion', 'local'
    error_sincronizacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

class Auditoria(Base):
    """
    Tabla de auditoría para operaciones con Google Sheets.
    """
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fila_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accion: Mapped[str] = mapped_column(String(50), nullable=False) # "crear", "editar"
    valores: Mapped[str] = mapped_column(Text, nullable=False) # JSON string
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente") # "pendiente", "éxito", "fallido"
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

class RutaTarifa(Base):
    """
    Tabla de tarifas por rutas (para la sección de Pago de Flete).
    """
    __tablename__ = "rutas_tarifas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ruta: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    precio: Mapped[float] = mapped_column(Float, default=0.0)
    sucursal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

# Inicialización
async def init_db():
    """
    Crea las tablas si no existen.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Base de datos SQLite inicializada correctamente.")

# CRUD de Camiones
async def obtener_todos_camiones() -> list[CamionDb]:
    async with async_session_factory() as session:
        # Ordenamos por sucursal y luego convertimos el nro a entero para ordenar numéricamente
        stmt = select(CamionDb).order_by(CamionDb.sucursal, CamionDb.fila_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

async def obtener_camion_por_placa(placa: str) -> CamionDb | None:
    async with async_session_factory() as session:
        stmt = select(CamionDb).where(CamionDb.placa == placa)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

async def obtener_camion_por_fila(fila_id: int) -> CamionDb | None:
    async with async_session_factory() as session:
        return await session.get(CamionDb, fila_id)

async def guardar_camiones_bulk(camiones_list: list[dict]):
    """
    Reemplaza TODO el contenido local con los datos del sheet.
    Deduplica por placa (conserva el primero).
    """
    async with async_session_factory() as session:
        await session.execute(delete(CamionDb))
        vistos = set()
        insertados = 0
        for item in camiones_list:
            placa = item["placa"]
            if placa in vistos:
                logger.warning("Placa duplicada ignorada en bulk insert: %s", placa)
                continue
            vistos.add(placa)
            session.add(CamionDb(
                fila_id=item["fila_id"],
                nro=item.get("nro"),
                placa=placa,
                estado_trabajo=item.get("estado_trabajo", "Fijo"),
                ruta=item.get("ruta", "local"),
                tipo_combustible=item.get("tipo_combustible", "GAS-GASOLINA"),
                costo_flete=item.get("costo_flete", 0.0),
                sucursal=item["sucursal"],
                capacidad_kg=item.get("capacidad_kg", 0),
                capacidad_maples=item.get("capacidad_maples", 0),
                capacidad_util_kg=item.get("capacidad_util_kg", 0.0),
                sistema_camion=item.get("sistema_camion", "SIN INFORMACIÓN"),
                modificado_por=item.get("modificado_por", ""),
                modificado_por_email=item.get("modificado_por_email", ""),
                estado_servicio=item.get("estado_servicio", "EN SERVICIO"),
                estado_sincronizacion="sincronizado"
            ))
            insertados += 1
        await session.commit()
        logger.info("Guardados %d camiones en SQLite de forma masiva (%d originales, %d duplicados ignorados)", insertados, len(camiones_list), len(camiones_list)-insertados)

async def upsert_camiones_desde_sheets(camiones_list: list[dict]):
    """
    Actualiza o inserta camiones respetando los que ya existen (por placa).
    Deduplica por placa (conserva el primero).
    Salta registros con placa vacía (garbage data).
    """
    async with async_session_factory() as session:
        # Obtener placas y fila_ids existentes
        existentes = await session.execute(select(CamionDb.placa, CamionDb.fila_id))
        placas_existentes = {}
        fila_ids_existentes = set()
        for row in existentes:
            placas_existentes[row[0]] = row[1]
            fila_ids_existentes.add(row[1])

        insertados = 0
        actualizados = 0
        vistos = set()
        for item in camiones_list:
            placa = item.get("placa", "").strip()
            if not placa:
                logger.warning("Placa vacía ignorada en upsert (fila_id=%s)", item.get("fila_id"))
                continue
            if placa in vistos:
                logger.warning("Placa duplicada ignorada en upsert: %s", placa)
                continue
            vistos.add(placa)
            if placa in placas_existentes:
                stmt = select(CamionDb).where(CamionDb.placa == placa)
                result = await session.execute(stmt)
                camion = result.scalar_one()
                # Solo actualizar fila_id si el nuevo valor no colisiona con otra fila
                nuevo_fila_id = item["fila_id"]
                if nuevo_fila_id != camion.fila_id and nuevo_fila_id in fila_ids_existentes:
                    logger.debug("fila_id %s ya existe para otra placa, conservando %s para placa %s",
                                 nuevo_fila_id, camion.fila_id, placa)
                else:
                    fila_ids_existentes.discard(camion.fila_id)
                    camion.fila_id = nuevo_fila_id
                    fila_ids_existentes.add(nuevo_fila_id)
                camion.nro = item.get("nro")
                camion.estado_trabajo = item.get("estado_trabajo", "Fijo")
                camion.ruta = item.get("ruta", "local")
                camion.tipo_combustible = item.get("tipo_combustible", "GAS-GASOLINA")
                camion.costo_flete = item.get("costo_flete", 0.0)
                camion.sucursal = item["sucursal"]
                camion.capacidad_kg = item.get("capacidad_kg", 0)
                camion.capacidad_maples = item.get("capacidad_maples", 0)
                camion.capacidad_util_kg = item.get("capacidad_util_kg", 0.0)
                camion.estado_sincronizacion = "sincronizado"
                actualizados += 1
            else:
                # Asignar fila_id que no colisione
                fila_id = item["fila_id"]
                while fila_id in fila_ids_existentes:
                    fila_id += 1
                fila_ids_existentes.add(fila_id)
                session.add(CamionDb(
                    fila_id=fila_id,
                    nro=item.get("nro"),
                    placa=placa,
                    estado_trabajo=item.get("estado_trabajo", "Fijo"),
                    ruta=item.get("ruta", "local"),
                    tipo_combustible=item.get("tipo_combustible", "GAS-GASOLINA"),
                    costo_flete=item.get("costo_flete", 0.0),
                    sucursal=item["sucursal"],
                    capacidad_kg=item.get("capacidad_kg", 0),
                    capacidad_maples=item.get("capacidad_maples", 0),
                    capacidad_util_kg=item.get("capacidad_util_kg", 0.0),
                    sistema_camion=item.get("sistema_camion", "SIN INFORMACIÓN"),
                    modificado_por=item.get("modificado_por", ""),
                    modificado_por_email=item.get("modificado_por_email", ""),
                    estado_servicio=item.get("estado_servicio", "EN SERVICIO"),
                    estado_sincronizacion="sincronizado"
                ))
                insertados += 1

        await session.commit()
        logger.info("Upsert desde Sheets: %d actualizados, %d insertados", actualizados, insertados)

        # ── Limpiar registros sincronizados que ya no existen en Sheets ───
        if vistos and len(vistos) > 5:
            stmt_delete = delete(CamionDb).where(
                CamionDb.estado_sincronizacion == "sincronizado",
                CamionDb.placa.notin_(vistos)
            )
            result = await session.execute(stmt_delete)
            if result.rowcount:
                logger.info("Eliminados %d camiones que ya no están en Sheets", result.rowcount)
                await session.commit()

async def crear_camion_local(camion_data: dict, fila_id: int, estado_sinc: str) -> CamionDb:
    async with async_session_factory() as session:
        camion = CamionDb(
            fila_id=fila_id,
            nro=camion_data.get("nro"),
            placa=camion_data["placa"],
            estado_trabajo=camion_data.get("estado_trabajo", "Fijo"),
            ruta=camion_data.get("ruta", "local"),
            tipo_combustible=camion_data.get("tipo_combustible", "GAS-GASOLINA"),
            costo_flete=camion_data.get("costo_flete", 0.0),
            sucursal=camion_data["sucursal"],
            capacidad_kg=camion_data.get("capacidad_kg", 0),
            capacidad_maples=camion_data.get("capacidad_maples", 0),
            capacidad_util_kg=camion_data.get("capacidad_util_kg", 0.0),
            sistema_camion=camion_data.get("sistema_camion", "SIN INFORMACIÓN"),
            estado_servicio=camion_data.get("estado_servicio", "EN SERVICIO"),
            modificado_por=camion_data.get("modificado_por", ""),
            modificado_por_email=camion_data.get("modificado_por_email", ""),
            estado_sincronizacion=estado_sinc
        )
        session.add(camion)
        await session.commit()
        await session.refresh(camion)
        return camion

async def actualizar_camion_local(fila_id: int, camion_data: dict, estado_sinc: str) -> CamionDb | None:
    async with async_session_factory() as session:
        camion = await session.get(CamionDb, fila_id)
        if not camion:
            return None
        
        for k, v in camion_data.items():
            if v is not None:
                setattr(camion, k, v)
        
        camion.estado_sincronizacion = estado_sinc
        await session.commit()
        await session.refresh(camion)
        return camion

async def marcar_sincronizado(fila_id: int, nuevo_fila_id_real: int | None = None):
    async with async_session_factory() as session:
        camion = await session.get(CamionDb, fila_id)
        if not camion:
            logger.warning("Camión con fila_id %s no encontrado para marcar como sincronizado", fila_id)
            return
        
        camion.estado_sincronizacion = "sincronizado"
        camion.error_sincronizacion = None
        
        if nuevo_fila_id_real is not None and nuevo_fila_id_real != fila_id:
            # Si se le asignó un nuevo ID real (por ejemplo, después de una inserción en Sheets)
            # Primero eliminamos el temporal e insertamos el real, o actualizamos la clave primaria
            # En SQLAlchemy actualizar la PK puede ser complejo; es más fácil recrearlo si cambia
            # Pero como calculamos fila_id = max_fila_id + 1 en el backend, nuevo_fila_id_real
            # suele ser idéntico al calculado. Si cambia, hacemos update del fila_id.
            # SQLite permite cambiar la PK directamente.
            camion.fila_id = nuevo_fila_id_real
            
        await session.commit()
        logger.debug("Camión fila %s marcado como sincronizado", fila_id)

async def marcar_error_sincronizacion(fila_id: int, error_msg: str):
    async with async_session_factory() as session:
        camion = await session.get(CamionDb, fila_id)
        if camion:
            camion.estado_sincronizacion = "error"
            camion.error_sincronizacion = error_msg
            await session.commit()
            logger.error("Camión fila %s marcado con error de sincronización: %s", fila_id, error_msg)

async def obtener_siguiente_nro_sucursal(sucursal: str) -> int:
    """Siguiente nro secuencial contando registros existentes de esa sucursal."""
    async with async_session_factory() as session:
        stmt = select(func.count()).select_from(CamionDb).where(CamionDb.sucursal == sucursal)
        result = await session.execute(stmt)
        return (result.scalar() or 0) + 1

async def obtener_max_fila_id() -> int:
    async with async_session_factory() as session:
        stmt = select(func.max(CamionDb.fila_id))
        result = await session.execute(stmt)
        val = result.scalar()
        return val if val is not None else 1 # Fila 1 es cabecera, así que retornamos 1 si no hay registros

async def obtener_pendientes_sincronizacion_count() -> int:
    async with async_session_factory() as session:
        stmt = select(func.count()).select_from(CamionDb).where(
            CamionDb.estado_sincronizacion.in_(["pendiente_insercion", "pendiente_actualizacion"])
        )
        result = await session.execute(stmt)
        return result.scalar() or 0

async def obtener_total_camiones_count() -> int:
    async with async_session_factory() as session:
        stmt = select(func.count()).select_from(CamionDb)
        result = await session.execute(stmt)
        return result.scalar() or 0

async def eliminar_camion_local(fila_id: int) -> bool:
    """Elimina un camión por fila_id. Retorna True si existía."""
    async with async_session_factory() as session:
        camion = await session.get(CamionDb, fila_id)
        if not camion:
            return False
        await session.delete(camion)
        await session.commit()
        logger.info("Camión fila_id %s eliminado", fila_id)
        return True

async def obtener_ultimo_cambio() -> tuple[str | None, str | None, str | None]:
    async with async_session_factory() as session:
        stmt = select(CamionDb.actualizado_en, CamionDb.modificado_por, CamionDb.modificado_por_email).order_by(CamionDb.actualizado_en.desc()).limit(1)
        result = await session.execute(stmt)
        row = result.first()
        if row:
            fecha = row[0].strftime("%d/%m/%Y %H:%M:%S") if row[0] else None
            return fecha, row[1] or None, row[2] or None
        return None, None, None

async def obtener_camiones_por_sucursal() -> dict[str, int]:
    async with async_session_factory() as session:
        stmt = select(CamionDb.sucursal, func.count()).group_by(CamionDb.sucursal).order_by(CamionDb.sucursal)
        result = await session.execute(stmt)
        return {row[0]: row[1] for row in result}

async def obtener_promedio_flete_por_sucursal() -> list[dict]:
    async with async_session_factory() as session:
        stmt = select(
            CamionDb.sucursal,
            func.avg(CamionDb.costo_flete),
            func.count(),
            func.sum(CamionDb.costo_flete)
        ).group_by(CamionDb.sucursal).order_by(CamionDb.sucursal)
        result = await session.execute(stmt)
        return [
            {
                "sucursal": row[0],
                "promedio_flete": round(row[1] or 0, 2),
                "total_camiones": row[2],
                "total_flete": round(row[3] or 0, 2)
            }
            for row in result
        ]

# CRUD de Auditoría
async def crear_registro_auditoria(
    fila_id: int | None,
    accion: str,
    valores: str,
) -> int:
    async with async_session_factory() as session:
        registro = Auditoria(
            fila_id=fila_id,
            accion=accion,
            valores=valores,
            estado="pendiente",
        )
        session.add(registro)
        await session.commit()
        await session.refresh(registro)
        return registro.id

async def actualizar_estado_auditoria(
    auditoria_id: int,
    estado: str,
    error: str | None = None,
):
    async with async_session_factory() as session:
        registro = await session.get(Auditoria, auditoria_id)
        if registro:
            registro.estado = estado
            registro.error = error
            await session.commit()

async def obtener_historial(limit: int = 50) -> list[Auditoria]:
    async with async_session_factory() as session:
        stmt = (
            select(Auditoria)
            .order_by(Auditoria.creado_en.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

# CRUD de Rutas Tarifas
async def obtener_rutas_tarifas(offset: int = 0, limit: int = 10) -> list[RutaTarifa]:
    """Obtiene tarifas paginadas."""
    async with async_session_factory() as session:
        stmt = select(RutaTarifa).order_by(RutaTarifa.creado_en.desc()).offset(offset).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

async def obtener_ruta_tarifa_por_nombre(ruta: str) -> RutaTarifa | None:
    """Obtiene una tarifa por nombre de ruta."""
    async with async_session_factory() as session:
        stmt = select(RutaTarifa).where(RutaTarifa.ruta == ruta)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

async def crear_ruta_tarifa(ruta: str, precio: float, sucursal: str | None = None, descripcion: str | None = None) -> RutaTarifa:
    """Crea una nueva tarifa de ruta."""
    async with async_session_factory() as session:
        registro = RutaTarifa(
            ruta=ruta,
            precio=precio,
            sucursal=sucursal,
            descripcion=descripcion,
        )
        session.add(registro)
        await session.commit()
        await session.refresh(registro)
        return registro

async def actualizar_ruta_tarifa(ruta: str, precio: float, sucursal: str | None = None, descripcion: str | None = None) -> RutaTarifa | None:
    """Actualiza una tarifa existente o crea una nueva si no existe."""
    async with async_session_factory() as session:
        stmt = select(RutaTarifa).where(RutaTarifa.ruta == ruta)
        result = await session.execute(stmt)
        registro = result.scalar_one_or_none()
        
        if registro:
            registro.precio = precio
            if sucursal is not None:
                registro.sucursal = sucursal
            if descripcion is not None:
                registro.descripcion = descripcion
            registro.actualizado_en = datetime.now(timezone.utc)
        else:
            registro = RutaTarifa(
                ruta=ruta,
                precio=precio,
                sucursal=sucursal,
                descripcion=descripcion,
            )
            session.add(registro)
        
        await session.commit()
        await session.refresh(registro)
        return registro

async def eliminar_ruta_tarifa(ruta: str) -> bool:
    """Elimina una tarifa por nombre de ruta."""
    async with async_session_factory() as session:
        stmt = select(RutaTarifa).where(RutaTarifa.ruta == ruta)
        result = await session.execute(stmt)
        registro = result.scalar_one_or_none()
        
        if registro:
            await session.delete(registro)
            await session.commit()
            return True
        return False

async def contar_rutas_tarifas() -> int:
    """Cuenta el total de tarifas registradas."""
    async with async_session_factory() as session:
        stmt = select(func.count()).select_from(RutaTarifa)
        result = await session.execute(stmt)
        return result.scalar() or 0
