import logging
from modules.rutas.db.database import init_db, seed_desde_excel, obtener_madres_con_hijas

logger = logging.getLogger(__name__)


async def init_module():
    logger.info("Iniciando módulo Rutas...")
    await init_db()

    existe = await obtener_madres_con_hijas()
    if existe:
        logger.info("Rutas ya existen en DB (%d madres), saltando seed", len(existe))
        return

    try:
        resultado = await seed_desde_excel()
        logger.info("Seed inicial de rutas: %d madres, %d hijas", resultado["madres"], resultado["hijas"])
    except FileNotFoundError:
        logger.warning("Archivo BBDDs_SL.xlsx no encontrado, saltando seed de rutas")
    except Exception as e:
        logger.error("Error en seed inicial de rutas: %s", e)


async def shutdown_module():
    logger.info("Deteniendo módulo Rutas...")
