"""
sheets.py — Conexión a Google Sheets para el módulo Jornaleros.

Reutiliza el mismo transporte del módulo de camiones (Apps Script Web App
o gspread como fallback), pero apunta a la hoja `Horas_Jornaleros`
(configurable con la env `JORNALEROS_SHEET_NAME`).
"""

import logging
import asyncio

import httpx

from modules.camiones.config import settings

logger = logging.getLogger(__name__)

# Formato de 15 columnas (13 originales + tarifa diaria + observaciones)
HEADERS_LIST = [
    "ID",
    "FECHA_INICIAL",
    "FECHA_FINAL",
    "TIPO_TRABAJADOR",
    "CD",
    "UNIDAD",
    "AREA",
    "CANTIDAD_JORNALEROS",
    "HORAS_TRABAJADAS",
    "DIAS_TRABAJADOS_TOTALES",
    "DIAS_TRABAJADOS_LABORALES",
    "LLENADO POR",
    "FECHA_CREACION",
    "TARIFA_DIARIA",
    "OBSERVACIONES",
]


def _col_letter(n: int) -> str:
    s = ""
    while n >= 0:
        s = chr(ord('A') + n % 26) + s
        n = n // 26 - 1
    return s


def _sheet_name() -> str:
    return settings.jornaleros_sheet_name or "Horas_Jornaleros"


class JornalerosSheetsClient:
    """Cliente de Google Sheets para jornaleros (modo apps_script o gspread)."""

    def __init__(self):
        self.enabled = False
        self._mode = "none"
        self._sheet = None
        self._worksheet = None

    async def initialize(self):
        # 1. OAuth 2.0 usuario — más confiable
        if settings.oauth_client_secret and settings.sheet_id:
            try:
                import gspread as _gspread
                import json as _json, os as _os, tempfile as _tf
                cr = settings.oauth_client_secret
                if cr.startswith("{"):
                    creds_path = _os.path.join(_tf.gettempdir(), "gspread_client_secret.json")
                    with open(creds_path, "w") as f:
                        f.write(cr)
                    auth_path = None
                    if settings.authorized_user_json:
                        auth_path = _os.path.join(_tf.gettempdir(), "gspread_authorized_user.json")
                        with open(auth_path, "w") as f:
                            f.write(settings.authorized_user_json)
                    gc = await asyncio.to_thread(
                        _gspread.oauth,
                        credentials_filename=creds_path,
                        authorized_user_filename=auth_path or "authorized_user.json"
                    )
                else:
                    gc = await asyncio.to_thread(
                        _gspread.oauth,
                        credentials_filename=cr,
                        authorized_user_filename="authorized_user.json"
                    )
                self._sheet = await asyncio.to_thread(gc.open_by_key, settings.sheet_id)
                self._worksheet = await self._obtener_o_crear_hoja()
                self._mode = "gspread"
                self.enabled = True
                logger.info("Modo Google Sheets (jornaleros): OAuth 2.0 usuario")
                return
            except Exception as e:
                logger.warning("OAuth 2.0 (jornaleros) falló: %s", e)

        # 2. Apps Script Web App (misma URL que camiones; acciones genéricas)
        if settings.apps_script_url and settings.apps_script_token:
            self._mode = "apps_script"
            self.enabled = True
            logger.info("Modo Google Sheets (jornaleros): Apps Script Web App")
            return

        # 3. Service Account (gspread)
        if settings.google_credentials_json and settings.sheet_id:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
                import json as _json
                creds_dict = _json.loads(settings.google_credentials_json)
                creds = Credentials.from_service_account_info(
                    creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"]
                )
                client = gspread.authorize(creds)
                self._sheet = client.open_by_key(settings.sheet_id)
                self._worksheet = await self._obtener_o_crear_hoja()
                self._mode = "gspread"
                self.enabled = True
                logger.info("Modo Google Sheets (jornaleros): gspread (fallback)")
                return
            except Exception as e:
                logger.warning("Fallback gspread (jornaleros) falló: %s", e)

        self.enabled = False
        self._mode = "none"
        logger.warning("Google Sheets NO configurado para jornaleros. Modo LOCAL.")

    async def _obtener_o_crear_hoja(self):
        nombre = _sheet_name()
        try:
            return await asyncio.to_thread(self._sheet.worksheet, nombre)
        except Exception:
            logger.info("Creando hoja '%s' en el spreadsheet", nombre)
            ws = await asyncio.to_thread(self._sheet.add_worksheet, nombre, rows=100, cols=len(HEADERS_LIST))
            return ws

    async def _call_apps_script(self, payload: dict) -> dict:
        payload["token"] = settings.apps_script_token
        payload["sheetName"] = _sheet_name()
        actions_get = ("getAll", "getRow", "deleteRow", "clear", "writeHeaders")
        use_get = payload.get("action") in actions_get
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            try:
                if use_get:
                    resp = await client.get(settings.apps_script_url, params=payload, headers=headers)
                else:
                    resp = await client.post(settings.apps_script_url, json=payload, headers=headers)
            except httpx.TimeoutException:
                return {"success": False, "error": "Apps Script no respondió (timeout)"}
            except httpx.ConnectError:
                return {"success": False, "error": "No se pudo conectar con Apps Script"}
            except Exception as e:
                return {"success": False, "error": f"Error HTTP: {e}"}

            try:
                return resp.json()
            except Exception:
                logger.error("Apps Script no devolvió JSON válido (status %s)", resp.status_code)
                return {"success": False, "error": f"JSON inválido del Apps Script ({resp.status_code})"}

    # ── Operaciones principales ─────────────────────────────────────────

    async def read_all_rows(self) -> dict:
        """Obtiene todas las filas de la hoja. Retorna {success, data: [ [fila], ... ]}."""
        if not self.enabled:
            return {"success": False, "data": []}
        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "getAllValues"})
        rows = await asyncio.to_thread(self._worksheet.get_all_values)
        return {"success": True, "data": rows}

    async def append_row(self, valores: list) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}
        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "append", "values": valores})
        try:
            await asyncio.to_thread(
                self._worksheet.append_row, valores, value_input_option="USER_ENTERED"
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"Error al apendar en sheets: {e}"}

    async def _buscar_fila_por_id(self, jornalero_id: str) -> int | None:
        """Devuelve el número de fila (1-based) donde está el ID en la columna A."""
        result = await self.read_all_rows()
        if not result.get("success"):
            return None
        for i, row in enumerate(result.get("data", [])):
            if row and str(row[0]).strip() == str(jornalero_id).strip():
                return i + 1
        return None

    async def update_row(self, fila: int, valores: list) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}
        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "update", "fila": fila, "values": valores})
        try:
            col_fin = _col_letter(len(valores) - 1)
            await asyncio.to_thread(
                self._worksheet.update, f"A{fila}:{col_fin}{fila}", [valores],
                value_input_option="USER_ENTERED"
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"Error al actualizar fila {fila}: {e}"}

    async def delete_row(self, fila: int) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}
        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "deleteRow", "fila": fila})
        try:
            await asyncio.to_thread(self._worksheet.delete_rows, fila)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"Error al eliminar fila {fila}: {e}"}

    async def upsert_row(self, jornalero_id: str, valores: list) -> dict:
        """Actualiza la fila del ID si existe; si no, la apenda al final."""
        fila = await self._buscar_fila_por_id(jornalero_id)
        if fila is not None:
            return await self.update_row(fila, valores)
        return await self.append_row(valores)

    async def delete_by_id(self, jornalero_id: str) -> dict:
        fila = await self._buscar_fila_por_id(jornalero_id)
        if fila is None:
            return {"success": False, "error": f"ID {jornalero_id} no encontrado en la hoja"}
        return await self.delete_row(fila)

    async def write_headers(self) -> dict:
        if not self.enabled:
            return {"success": False}
        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "writeHeaders", "headers": HEADERS_LIST})
        col_fin = _col_letter(len(HEADERS_LIST) - 1)
        await asyncio.to_thread(self._worksheet.update, f"A1:{col_fin}1", [HEADERS_LIST])
        return {"success": True}

    async def set_all_rows(self, headers: list, rows: list[list]) -> dict:
        """Reescribe TODA la hoja en un solo request (headers + data).
        Misma lógica que el módulo de camiones (acción 'setAll')."""
        if not self.enabled:
            return {"success": False, "error": "No disponible"}
        if self._mode == "apps_script":
            return await self._call_apps_script({
                "action": "setAll",
                "headers": headers,
                "data": rows,
            })
        try:
            col_fin = _col_letter(len(headers) - 1)
            all_rows = [headers] + rows
            rango = f"A1:{col_fin}{len(all_rows)}"
            await asyncio.to_thread(self._worksheet.clear)
            await asyncio.to_thread(
                self._worksheet.update, rango, all_rows,
                value_input_option="USER_ENTERED"
            )
            return {"success": True, "data": len(rows)}
        except Exception as e:
            return {"success": False, "error": f"Error al reescribir la hoja: {e}"}


jornaleros_sheets_client = JornalerosSheetsClient()
