"""
migrate_rutas.py — One-time migration: asigna ruta a camiones desde el módulo Rutas.

Uso:
    update-sheet-app\\venv\\Scripts\\python migrate_rutas.py
    update-sheet-app\\venv\\Scripts\\python migrate_rutas.py --push-sheet
"""
import asyncio, sys, os, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PUSH_SHEET = "--push-sheet" in sys.argv

SUCURSAL_MAP = {
    "SANTA CRUZ": "SCZ.",
    "LA PAZ": "LP-EA.",
    "COCHABAMBA": "CBBA.",
}

# Ruta madre default por sucursal (más representativa que la primera alfabética)
DEFAULT_RUTA = {
    "SCZ.": "MERCADO",
    "LP-EA.": "EL ALTO",
    "CBBA.": "RUTAS LOCALES",
}


async def main():
    from modules.camiones.db.database import (
        init_db as c_init, async_session_factory as c_session, CamionDb, select,
    )
    from modules.rutas.db.database import (
        init_db as r_init, async_session_factory as r_session, RutaMadreDb,
    )
    await c_init()
    await r_init()

    # ── 1. Leer rutas madre ──
    async with r_session() as rs:
        r = await rs.execute(
            select(RutaMadreDb.sucursal, RutaMadreDb.nombre)
            .distinct().order_by(RutaMadreDb.sucursal, RutaMadreDb.nombre)
        )
        madres = list(r.all())

    sucursal_madres = {}
    for suc, nombre in madres:
        suc_upper = suc.strip().upper()
        sucursal_madres.setdefault(suc_upper, []).append(nombre)

    logger.info("Rutas madre cargadas: %d en %d sucursales", len(madres), len(sucursal_madres))

    # ── 2. Actualizar camiones dentro de UNA sesión ──
    async with c_session() as session:
        result = await session.execute(select(CamionDb))
        camiones = list(result.scalars().all())
        logger.info("Camiones en DB: %d", len(camiones))

        updates = []
        for c in camiones:
            suc_raw = (c.sucursal or "").strip().upper()
            ruta_suc = SUCURSAL_MAP.get(suc_raw)
            if not ruta_suc:
                continue
            madres_available = sucursal_madres.get(ruta_suc.upper(), [])
            if not madres_available:
                continue

            ruta_actual = (c.ruta or "").strip()
            default_ruta = DEFAULT_RUTA.get(ruta_suc, madres_available[0])
            if ruta_actual == default_ruta:
                continue
            c.ruta = default_ruta
            updates.append((c.placa, default_ruta, ruta_suc))

        await session.commit()
        logger.info("Camiones actualizados: %d", len(updates))
        for placa, ruta, suc in updates[:5]:
            logger.info("  %s → %s (%s)", placa, ruta, suc)
        if len(updates) > 5:
            logger.info("  ... y %d más", len(updates) - 5)

    # ── 3. Deducir ruta_madre desde ruta ──
    from modules.camiones.db.database import poblar_ruta_madre_desde_ruta
    poblados = await poblar_ruta_madre_desde_ruta()
    logger.info("ruta_madre deducidas: %d", poblados)

    # ── 4. Verificar ──
    async with c_session() as session:
        result = await session.execute(select(CamionDb))
        camiones = list(result.scalars().all())
        from collections import Counter
        rutas = Counter()
        madres = Counter()
        for c in camiones:
            rutas[c.ruta or ""] += 1
            madres[c.ruta_madre or ""] += 1
        logger.info("Resultado final — RUTAS: %s", dict(rutas.most_common()))
        logger.info("Resultado final — RUTA_MADRE: %s", dict(madres.most_common()))

    # ── 5. Push a Google Sheet (opcional, requiere Code.gs actualizado con ensureRutaColumn) ──
    if PUSH_SHEET:
        logger.info("Subiendo rutas al Google Sheet...")
        import httpx
        from modules.camiones.config import settings
        url = settings.apps_script_url
        try:
            r = httpx.get(url, params={
                "token": "pablo9090",
                "action": "ensureRutaColumn",
            }, timeout=60, follow_redirects=True)
            data = r.json()
            if data.get("success"):
                logger.info("Sheet actualizado: %s", data["data"])
            else:
                logger.warning("ensureRutaColumn no disponible: %s", data.get("error"))
        except Exception as e:
            logger.error("Error al llamar ensureRutaColumn: %s", e)

    logger.info("Migracion completada.")


if __name__ == "__main__":
    asyncio.run(main())
