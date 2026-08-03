"""
lifecycle.py — Inicialización del módulo Jornaleros.
"""

import logging

from modules.jornaleros.db.database import init_db, seed_desde_excel, contar_jornaleros
from modules.jornaleros.sheets import jornaleros_sheets_client
from modules.jornaleros.routes import update_queue

logger = logging.getLogger(__name__)


async def init_module():
    logger.info("Iniciando módulo Jornaleros...")
    await init_db()

    existe = await contar_jornaleros()
    if existe:
        logger.info("Jornaleros ya existen en DB (%d registros), saltando seed", existe)
    else:
        try:
            resultado = await seed_desde_excel()
            logger.info("Seed inicial de jornaleros: %d creados, %d actualizados, %d omitidos",
                        resultado["creados"], resultado["actualizados"], resultado["omitidos"])
        except FileNotFoundError:
            logger.warning("DB_PROD_GDN.xlsx no encontrado, saltando seed de jornaleros")
        except Exception as e:
            logger.error("Error en seed inicial de jornaleros: %s", e)

    try:
        await jornaleros_sheets_client.initialize()
    except Exception as e:
        logger.warning("Sheets de jornaleros no inicializado: %s", e)

    await update_queue.start()
    logger.info("Módulo Jornaleros listo.")


async def shutdown_module():
    logger.info("Deteniendo módulo Jornaleros...")
    await update_queue.stop()
