"""
bootstrap.py — Lee los 3 archivos HTML fuente, deduplica por placa,
omite ruteos, y escribe en Google Sheets vía la API de Apps Script.
"""

import re
import json
import logging
import httpx
from pathlib import Path

from modules.camiones.config import settings

logger = logging.getLogger(__name__)

BASE_DIR = Path(r"C:\Users\lenov\Desktop\CAMIONES")


def parse_html_table(filepath: str):
    """Extrae celdas de todas las filas <tr> de un HTML de Google Sheets."""
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL)
    result = []
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
        texts = []
        for c in cells:
            c = re.sub(r"<[^>]+>", "", c)
            c = c.replace("&nbsp;", "").strip()
            c = c.replace("\xa0", "").strip()
            texts.append(c)
        if texts:
            result.append(texts)
    return result


def parse_lista_camiones(rows: list[list[str]]):
    """LISTA CAMIONES 2024.html: [propietario, placa, tipo, canastillos, cap_kg, maples, mples_kg, ruta]"""
    out = {}
    for row in rows[1:]:  # skip header
        if len(row) < 8:
            continue
        placa = row[1].strip().upper()
        if not placa:
            continue
        ruta = row[7].strip().upper()
        # omitir RUTEO
        if "RUTEO" in ruta:
            continue
        sistema = row[2].strip().upper()
        # normalizar
        if "HIBRIDO" in sistema:
            sistema = "HIBRIDO"
        elif "REFRIGERADO" in sistema:
            sistema = "REFRIGERADO"
        elif "CONGELADO" in sistema:
            sistema = "REFRIGERADO"
        elif "SECO" in sistema:
            sistema = "SECOS"
        else:
            sistema = "SIN INFORMACIÓN"
        out[placa] = {
            "placa": placa,
            "sistema_camion": sistema,
            "capacidad_kg": int(row[4]) if row[4].replace(".", "").isdigit() else 0,
            "capacidad_maples": int(row[5]) if row[5].replace(".", "").isdigit() else 0,
            "capacidad_util_kg": float(row[6]) if row[6].replace(".", "").isdigit() else 0.0,
            "ruta": row[7].strip(),
            "estado_servicio": "EN SERVICIO",
        }
    return out


def parse_db(rows: list[list[str]]):
    """DB.html: [proveedor, placa, cap_nominal, cap_util, canastillos, maples, mples_kg, cap_75, ruta, sistema]"""
    out = {}
    for row in rows[1:]:
        if len(row) < 10:
            continue
        placa = row[1].strip().upper()
        if not placa:
            continue
        sistema = row[9].strip().upper()
        if "HIBRIDO" in sistema:
            sistema = "HIBRIDO"
        elif "REFRIGERADO" in sistema:
            sistema = "REFRIGERADO"
        elif "SECO" in sistema or "SECOS" in sistema:
            sistema = "SECOS"
        else:
            sistema = "SIN INFORMACIÓN"
        out[placa] = {
            "placa": placa,
            "sistema_camion": sistema,
            "capacidad_kg": int(row[3]) if row[3].replace(".", "").isdigit() else 0,
            "capacidad_maples": int(row[5]) if row[5].replace(".", "").isdigit() else 0,
            "capacidad_util_kg": float(row[6]) if row[6].replace(".", "").isdigit() else 0.0,
            "ruta": row[8].strip(),
            "estado_servicio": "EN SERVICIO",
        }
    return out


def parse_hoja1(rows: list[list[str]]):
    """Hoja1.html: [tipo_ruta, placa, sistema, canastillos, cap_kg, maples1, cap_75, maples2, mples_kg, obs]"""
    out = {}
    for row in rows[1:]:
        if len(row) < 10:
            continue
        placa = row[1].strip().upper()
        if not placa:
            continue
        sistema = row[2].strip().upper()
        if "HIBRIDO" in sistema:
            sistema = "HIBRIDO"
        elif "REFRIGERADO" in sistema:
            sistema = "REFRIGERADO"
        elif "SECO" in sistema or "SECOS" in sistema:
            sistema = "SECOS"
        elif "3 COMPARTIMIENTOS" in sistema:
            sistema = "3 COMPARTIMIENTOS"
        else:
            sistema = "SIN INFORMACIÓN"
        tipo_ruta = row[0].strip().upper()
        obs = row[9].strip().upper() if len(row) > 9 else ""
        if tipo_ruta == "RETIRADO":
            estado = "FUERA DE SERVICIO"
        elif obs == "PREGUNTAR":
            estado = "CONSULTAR"
        else:
            estado = "EN SERVICIO"
        out[placa] = {
            "placa": placa,
            "sistema_camion": sistema,
            "capacidad_kg": int(row[4]) if row[4].replace(".", "").isdigit() else 0,
            "capacidad_maples": int(row[7]) if len(row) > 7 and row[7].replace(".", "").isdigit() else 0,
            "capacidad_util_kg": float(row[8]) if len(row) > 8 and row[8].replace(".", "").isdigit() else 0.0,
            "ruta": row[0].strip(),
            "estado_servicio": estado,
        }
    return out


def merge_dedup(sources: list[dict]) -> list[dict]:
    """Merge multiple {placa: data} dicts, keeping first occurrence."""
    seen = {}
    for src in sources:
        for placa, data in src.items():
            if placa not in seen:
                seen[placa] = data
    return list(seen.values())


async def bootstrap_sheets(force_write: bool = False):
    """Lee los 3 HTML, mergea, y opcionalmente escribe en Google Sheets."""
    files = {
        "LISTA CAMIONES 2024.html": parse_lista_camiones,
        "DB.html": parse_db,
        "Hoja1.html": parse_hoja1,
    }
    sources = []
    for fname, parser in files.items():
        path = BASE_DIR / fname
        if not path.exists():
            logger.warning("Archivo no encontrado: %s", path)
            continue
        rows = parse_html_table(str(path))
        data = parser(rows)
        sources.append(data)
        logger.info("%s: %d registros", fname, len(data))

    merged = merge_dedup(sources)
    logger.info("Total merged (dedup): %d camiones", len(merged))

    if not force_write:
        logger.info("Modo dry-run. Para escribir pasar force_write=True")
        return merged

    if not settings.apps_script_url or not settings.apps_script_token:
        logger.error("APPS_SCRIPT_URL o APPS_SCRIPT_TOKEN no configurados")
        return merged

    # Escribir encabezados
    headers = [
        "Nº", "Nº placa", "Estado de trabajo",
        "Tipo de combustible", "Costo flete (Bs/viaje)", "Sucursal",
        "Capacidad en KG", "Capacidad de carga útil en maples",
        "Capacidad de carga útil en Kg", "Sistema Camión"
    ]
    payload_headers = {
        "action": "writeHeaders",
        "headers": headers,
        "token": settings.apps_script_token
    }
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        await client.post(settings.apps_script_url, json=payload_headers)
        logger.info("Encabezados escritos")

    # Escribir datos
    for idx, item in enumerate(merged):
        nro_suc = {}  # per-sucursal counter
        suc = item.get("sucursal", "La Paz")
        nro_suc[suc] = nro_suc.get(suc, 0) + 1
        fila = idx + 2  # fila 2 en adelante
        values = [
            str(nro_suc[suc]),
            item["placa"],
            "Fijo",
            "GAS-GASOLINA",
            "0",
            suc,
            str(item.get("capacidad_kg", 0)),
            str(item.get("capacidad_maples", 0)),
            str(item.get("capacidad_util_kg", 0.0)),
            item.get("sistema_camion", "SIN INFORMACIÓN"),
        ]
        payload = {
            "action": "append",
            "values": values,
            "token": settings.apps_script_token
        }
        try:
            resp = await client.post(settings.apps_script_url, json=payload)
            if resp.status_code != 200:
                logger.error("Error fila %d (%s): %s", fila, item["placa"], resp.text[:200])
        except Exception as e:
            logger.error("Error fila %d (%s): %s", fila, item["placa"], e)
        if (idx + 1) % 10 == 0:
            logger.info("Procesados %d/%d", idx + 1, len(merged))

    logger.info("Bootstrap completado: %d camiones escritos", len(merged))
    return merged
