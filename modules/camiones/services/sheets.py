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
    "Sistema Camión"
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
        # 1. Intentar con Apps Script
        if settings.apps_script_url and settings.apps_script_token:
            self._mode = "apps_script"
            self.enabled = True
            logger.info("Modo Google Sheets: Apps Script Web App")
            return

        # 2. Fallback con gspread
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
        """Llama al Apps Script Web App con POST, siguiendo redirects."""
        payload["token"] = settings.apps_script_token
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            try:
                resp = await client.post(settings.apps_script_url, json=payload)
            except httpx.TimeoutException:
                return {"success": False, "error": "Apps Script no respondió (timeout)"}
            except httpx.ConnectError:
                return {"success": False, "error": "No se pudo conectar con Apps Script"}
            except Exception as e:
                return {"success": False, "error": f"Error HTTP: {e}"}

            ct = resp.headers.get("content-type", "")
            if "application/json" not in ct and "text/json" not in ct:
                logger.error("Apps Script no devolvió JSON. Status: %s, Content-Type: %s", resp.status_code, ct)
                logger.error("Cuerpo (primeros 300): %s", resp.text[:300])
                return {"success": False, "error": f"Respuesta no JSON ({resp.status_code})"}
            try:
                return resp.json()
            except Exception:
                return {"success": False, "error": "JSON inválido del Apps Script"}

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

    async def append_row(self, valores: list) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "append", "values": valores})

        # Fallback gspread
        res = await asyncio.to_thread(self._worksheet.append_row, valores, value_input_option="USER_ENTERED")
        return {"success": True, "data": res}

    async def update_row(self, fila: int, valores: list) -> dict:
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "update", "fila": fila, "values": valores})

        # Fallback gspread
        col_fin = chr(ord('A') + len(valores) - 1)
        await asyncio.to_thread(
            self._worksheet.update, f"A{fila}:{col_fin}{fila}", [valores],
            value_input_option="USER_ENTERED"
        )
        return {"success": True, "data": fila}

    async def delete_row(self, fila: int) -> dict:
        """
        Elimina una fila específica del sheet (desplaza filas hacia arriba).
        """
        if not self.enabled:
            return {"success": False, "error": "No disponible"}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "deleteRow", "fila": fila})

        # Fallback gspread: clear content de la fila
        col_fin = "K"
        await asyncio.to_thread(
            self._worksheet.batch_clear, [f"A{fila}:{col_fin}{fila}"]
        )
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
        col_fin = chr(ord('A') + len(headers) - 1)
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
            col_fin = chr(ord('A') + cols - 1)
            await asyncio.to_thread(self._worksheet.batch_clear, [f"A2:{col_fin}{rows}"])
        return {"success": True}

    async def write_headers(self) -> dict:
        if not self.enabled:
            return {"success": False}

        if self._mode == "apps_script":
            return await self._call_apps_script({"action": "writeHeaders", "headers": HEADERS_LIST})

        col_fin = chr(ord('A') + len(HEADERS_LIST) - 1)
        await asyncio.to_thread(self._worksheet.update, f"A1:{col_fin}1", [HEADERS_LIST])
        return {"success": True}


sheets_client = GoogleSheetsClient()
