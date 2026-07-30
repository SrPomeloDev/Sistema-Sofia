"""
sheets.py — Conexión a Google Sheets vía Apps Script Web App (principal)
            o gspread (fallback).
"""

import json
import logging
import asyncio
from urllib.parse import urlencode

import httpx

from modules.camiones.config import settings

logger = logging.getLogger(__name__)


def _col_letter(n: int) -> str:
    """Convierte un índice 0-based a letra de columna (A, B, ..., Z, AA, AB...)."""
    s = ""
    while n >= 0:
        s = chr(ord('A') + n % 26) + s
        n = n // 26 - 1
    return s

HEADERS_LIST = [
    "Nº",
    "Nº placa ",
    "Estado de trabajo",
    "Tipo de combustible",
    "Costo flete (Bs/viaje)",
    "Sucursal",
    "Capacidad en KG",
    "Capacidad de carga útil en maples",
    "Capacidad de carga útil en Kg",
    "Sistema Camión",
    "Estado Servicio",
]


class GoogleSheetsClient:
    """
    Cliente de Google Sheets usando Apps Script Web App como puente.

    Si no hay APPS_SCRIPT_URL configurada, intenta con gspread como fallback.
    """

    def __init__(self):
        self.enabled = False
        self._mode = "none"  # "apps_script", "gspread", "none"
        self._client = None
        self._worksheet = None

    async def initialize(self):
        # 1. OAuth 2.0 usuario (client_secret.json) — más confiable
        if settings.oauth_client_secret and settings.sheet_id and settings.sheet_name:
            try:
                import gspread as _gspread
                import json as _json
                cr = settings.oauth_client_secret
                # Si la variable es un JSON inline, parsearlo; si no, es ruta a archivo
                if cr.startswith("{"):
                    creds_dict = _json.loads(cr)
                    auth_info = _json.loads(settings.authorized_user_json) if settings.authorized_user_json else None
                    if auth_info:
                        from google.oauth2.credentials import Credentials as _Creds
                        creds = _Creds.from_authorized_user_info(auth_info)
                        gc = await asyncio.to_thread(_gspread.authorize, creds)
                    else:
                        gc = await asyncio.to_thread(_gspread.oauth_from_dict, creds_dict)
                else:
                    gc = await asyncio.to_thread(
                        _gspread.oauth,
                        credentials_filename=cr,
                        authorized_user_filename="authorized_user.json"
                    )
                self._sheet = await asyncio.to_thread(gc.open_by_key, settings.sheet_id)
                self._worksheet = await asyncio.to_thread(self._sheet.worksheet, settings.sheet_name)
                self._mode = "gspread"
                self.enabled = True
                logger.info("Modo Google Sheets: OAuth 2.0 usuario")
                return
            except Exception as e:
                logger.warning("OAuth 2.0 falló: %s", e)

        # 2. Apps Script Web App
        if settings.apps_script_url and settings.apps_script_token:
            self._mode = "apps_script"
            self.enabled = True
            logger.info("Modo Google Sheets: Apps Script Web App")
            return

        # 3. Service Account (gspread)
        if settings.google_credentials_json and settings.sheet_id and settings.sheet_name:
            try:
                import gspread
                from google.oauth2.service_account import Credentials
                creds_dict = json.loads(settings.google_credentials_json)
                creds = Credentials.from_service_account_info(
                    creds_dict,
                    scopes=["https://www.googleapis.com/auth/spreadsheets"]
                )
                self._client = gspread.authorize(creds)
                self._sheet = self._client.open_by_key(settings.sheet_id)
                self._worksheet = self._sheet.worksheet(settings.sheet_name)
                self._mode = "gspread"
                self.enabled = True
                logger.info("Modo Google Sheets: gspread (fallback)")
                return
            except Exception as e:
                logger.warning("Fallback gspread falló: %s", e)

        self.enabled = False
        self._mode = "none"
        logger.warning("Google Sheets NO configurado. Modo LOCAL.")

    async def _call_apps_script(self, payload: dict) -> dict:
        """Llama al Apps Script Web App.
        Usa GET con query params para actions livianas (evita bloqueo 401 de Google).
        Usa POST con JSON para actions con datos grandes (setAll, append, update).
        """
        payload["token"] = settings.apps_script_token
        actions_get = ("getAll", "getRow", "deleteRow", "deleteByPlaca", "clear", "writeHeaders", "ensureRutaColumn")
        use_get = payload.get("action") in actions_get
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
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
                logger.error("Apps Script no devolvió JSON válido. Status: %s, Content-Type: %s", resp.status_code, resp.headers.get("content-type", ""))
                logger.error("Cuerpo (primeros 300): %s", resp.text[:300])
                return {"success": False, "error": f"JSON inválido del Apps Script ({resp.status_code})"}

    # ── Operaciones principales (usadas por main.py) ───────────────────

    async def read_all_rows(self) -> dict:
        """
        Obtiene todos los camiones desde Apps Script.
        Retorna el JSON crudo del script: {success, data: [...]}
        """
        if not self.enabled:
            return {"success": False, "data": []}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "getAll"})

        # Fallback gspread
        rows = await asyncio.to_thread(self._worksheet.get_all_values)
        return {"success": True, "data": rows}

    async def get_row(self, fila: int) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "getRow", "fila": fila})

        # Fallback gspread
        row = await asyncio.to_thread(self._worksheet.row_values, fila)
        return {"success": True, "data": row}

    async def append_row(self, valores: list, fila: int | None = None) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "append", "values": valores})

        # gspread: escribir en la fila indicada, o detectar última fila
        if fila is not None:
            col_fin = _col_letter(len(valores) - 1)
            try:
                await asyncio.to_thread(
                    self._worksheet.update, f"A{fila}:{col_fin}{fila}",
                    [valores], value_input_option="USER_ENTERED"
                )
                return {"success": True, "data": {"fila_insertada": fila}}
            except Exception as e:
                return {"success": False, "error": f"Error al escribir en fila {fila}: {e}"}
        # Sin fila: usar append_row (table detection)
        res = await asyncio.to_thread(self._worksheet.append_row, valores, value_input_option="USER_ENTERED")
        return {"success": True, "data": res}

    async def update_row(self, fila: int, valores: list) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "update", "fila": fila, "values": valores})

        # Fallback gspread
        col_fin = _col_letter(len(valores) - 1)
        await asyncio.to_thread(
            self._worksheet.update, f"A{fila}:{col_fin}{fila}", [valores],
            value_input_option="USER_ENTERED"
        )
        return {"success": True, "data": fila}

    async def delete_by_placa(self, placa: str) -> dict:
        """Elimina una fila del sheet buscando por placa."""
        if not self.enabled:
            return {"success": False, "error": "No disponible"}
        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "deleteByPlaca", "placa": placa})
        # gspread: buscar placa en columna B y eliminar fila
        try:
            col_b = await asyncio.to_thread(self._worksheet.col_values, 2)
        except Exception as e:
            return {"success": False, "error": f"No se pudo leer columna B: {e}"}
        for i, val in enumerate(col_b):
            if val.strip() == placa.strip():
                fila = i + 1
                try:
                    await asyncio.to_thread(self._worksheet.delete_rows, fila)
                except Exception as e:
                    return {"success": False, "error": f"Error al eliminar fila {fila}: {e}"}
                return {"success": True, "data": {"fila": fila, "placa": placa}}
        return {"success": False, "error": f"Placa {placa} no encontrada en el sheet"}

    async def delete_row(self, fila: int) -> dict:
        """
        Elimina una fila específica del sheet (desplaza filas hacia arriba).
        """
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "deleteRow", "fila": fila})

        # gspread: delete real de la fila
        try:
            await asyncio.to_thread(self._worksheet.delete_rows, fila)
        except Exception as e:
            return {"success": False, "error": f"Error al eliminar fila {fila}: {e}"}
        return {"success": True, "data": fila}

    async def set_all_rows(self, headers: list, rows: list[list]) -> dict:
        """
        Envía TODAS las filas en un solo request (headers + data).
        El Apps Script debe tener una acción 'setAll' que reciba { headers, data }.
        """
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({
                "action": "setAll",
                "headers": headers,
                "data": rows
            })

        # Fallback gspread: batch update completo
        col_fin = _col_letter(len(headers) - 1)
        all_rows = [headers] + rows
        rango = f"A1:{col_fin}{len(all_rows)}"
        await asyncio.to_thread(
            self._worksheet.update, rango, all_rows,
            value_input_option="USER_ENTERED"
        )
        return {"success": True, "data": len(rows)}

    async def clear_sheet(self) -> dict:
        if not self.enabled:
            return {"success": False}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "clear"})

        rows = self._worksheet.row_count
        cols = self._worksheet.col_count
        if rows > 1:
            col_fin = _col_letter(cols - 1)
            await asyncio.to_thread(self._worksheet.batch_clear, [f"A2:{col_fin}{rows}"])
        return {"success": True}

    async def write_headers(self) -> dict:
        if not self.enabled:
            return {"success": False}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "writeHeaders", "headers": HEADERS_LIST})

        col_fin = _col_letter(len(HEADERS_LIST) - 1)
        await asyncio.to_thread(self._worksheet.update, f"A1:{col_fin}1", [HEADERS_LIST])
        return {"success": True}


sheets_client = GoogleSheetsClient()
