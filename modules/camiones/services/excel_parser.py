import zipfile
import xml.etree.ElementTree as ET
import os
import logging

logger = logging.getLogger(__name__)

def parse_excel_camiones(file_path: str) -> list[dict]:
    """
    Parses 'CAMIONES FIJOS NACIONAL HUEVO.xlsx' using standard libraries.
    Returns a list of dictionaries representing truck records.
    """
    if not os.path.exists(file_path):
        logger.error("Excel file not found at path: %s", file_path)
        return []

    logger.info("Parsing Excel file: %s", file_path)
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            # 1. Parse shared strings
            shared_strings = []
            if 'xl/sharedStrings.xml' in z.namelist():
                ss_xml = z.read('xl/sharedStrings.xml')
                root = ET.fromstring(ss_xml)
                ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                for si in root.findall('ns:si', ns):
                    t_elements = si.findall('.//ns:t', ns)
                    val = "".join([t.text for t in t_elements if t.text])
                    shared_strings.append(val)

            # 2. Find first sheet
            ws_xml = z.read('xl/worksheets/sheet1.xml')
            root = ET.fromstring(ws_xml)
            ns = {'ns': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}

            # 3. Read rows
            rows_data = {}
            for row in root.findall('.//ns:row', ns):
                row_idx_str = row.attrib.get('r')
                if not row_idx_str:
                    continue
                row_idx = int(row_idx_str)
                row_cells = {}
                for cell in row.findall('ns:c', ns):
                    r_ref = cell.attrib.get('r') # e.g. "A1"
                    if not r_ref:
                        continue
                    t_type = cell.attrib.get('t') # "s" for shared string, etc.
                    val_el = cell.find('ns:v', ns)
                    val = ""
                    if val_el is not None and val_el.text:
                        val = val_el.text
                        if t_type == 's':
                            idx = int(val)
                            if idx < len(shared_strings):
                                val = shared_strings[idx]
                    # Extract column letter (e.g. "A1" -> "A")
                    col_letter = "".join([c for c in r_ref if c.isalpha()])
                    row_cells[col_letter] = val.strip()
                rows_data[row_idx] = row_cells

            # 4. Map columns to dictionary keys
            # Expecting header in Row 1.
            # Row 1 columns: A: Nº, B: Placa, C: Estado de trabajo, D: Ruta, E: Combustible,
            # F: Costo flete, G: Sucursal, H: Capacidad KG, I: Maples, J: Capacidad útil KG
            mapped_records = []
            sorted_rows = sorted(rows_data.keys())
            
            # Row 1 is header, skip it.
            for r in sorted_rows[1:]:
                cells = rows_data[r]
                # If row is completely empty, skip it.
                if not any(cells.values()):
                    continue
                
                # Check for plate (column B). If it's missing, it's probably not a valid truck row.
                placa = cells.get('B', '').strip()
                if not placa:
                    continue

                # Cast numeric values helper
                def to_float(val, default=0.0):
                    if not val:
                        return default
                    try:
                        return float(val.replace(',', '.'))
                    except ValueError:
                        return default

                def to_int(val, default=0):
                    if not val:
                        return default
                    try:
                        return int(float(val.replace(',', '.')))
                    except ValueError:
                        return default

                record = {
                    "fila_id": r,
                    "nro": cells.get('A', '').strip(),
                    "placa": placa,
                    "estado_trabajo": cells.get('C', 'Fijo').strip(),
                    "ruta": cells.get('D', 'local').strip(),
                    "tipo_combustible": cells.get('E', 'GAS-GASOLINA').strip(),
                    "costo_flete": to_float(cells.get('F', '0')),
                    "sucursal": cells.get('G', '').strip(),
                    "capacidad_kg": to_int(cells.get('H', '0')),
                    "capacidad_maples": to_int(cells.get('I', '0')),
                    "capacidad_util_kg": to_float(cells.get('J', '0')),
                }
                mapped_records.append(record)

            logger.info("Successfully parsed %d truck records from Excel", len(mapped_records))
            return mapped_records
    except Exception as e:
        logger.error("Error parsing Excel file %s: %s", file_path, e, exc_info=True)
        return []
