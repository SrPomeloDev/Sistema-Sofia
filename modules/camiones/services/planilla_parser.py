"""
planilla_parser.py — Parsea PLANILLA DE MÉTODOS PARA PAGOS.xlsx
y extrae promedios de flete por RUTA MADRE EBS.
"""

import logging
import os
from collections import defaultdict

logger = logging.getLogger(__name__)

PLANILLA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "PLANILLA DE MÉTODOS PARA PAGOS.xlsx",
)


def parse_planilla(file_path: str | None = None) -> list[dict]:
    """
    Lee el Excel y retorna lista de promedios por RUTA MADRE EBS.
    Cada dict: {ruta, precio, sucursal, descripcion, origen}
    """
    path = file_path or PLANILLA_PATH
    if not os.path.exists(path):
        logger.error("Planilla no encontrada: %s", path)
        return []

    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl no instalado. pip install openpyxl")
        return []

    try:
        wb = openpyxl.load_workbook(path, data_only=True)
    except Exception as e:
        logger.error("Error al abrir planilla: %s", e)
        return []

    ws = wb.active
    if ws is None:
        logger.error("No hay hoja activa en la planilla")
        wb.close()
        return []

    grupos: dict[str, list[float]] = defaultdict(list)
    ejemplos: dict[str, str] = {}

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 9:
            continue
        madre = str(row[4] or "").strip() if row[4] else ""
        flete = row[8]
        if not madre:
            continue
        try:
            precio = float(flete) if flete else 0.0
        except (ValueError, TypeError):
            precio = 0.0
        grupos[madre].append(precio)
        if madre not in ejemplos:
            hija = str(row[3] or "").strip() if row[3] else ""
            ejemplos[madre] = hija

    wb.close()

    resultados = []
    for madre, precios in sorted(grupos.items()):
        promedio = round(sum(precios) / len(precios), 2)
        resultados.append({
            "ruta": madre,
            "precio": promedio,
            "sucursal": None,
            "descripcion": f"Promedio de {len(precios)} registros. Ej: {ejemplos.get(madre, '')}",
            "origen": madre,
        })

    logger.info("Planilla parseada: %d rutas madre encontradas", len(resultados))
    return resultados
