"""
config.py — Carga de variables de entorno desde .env usando python-dotenv.

¿Por qué no pydantic-settings?
pydantic-settings tiene un bug conocido que causa bloqueo al leer .env
en ciertos entornos Windows. python-dotenv es más ligero y predecible.
"""

import os
from dotenv import load_dotenv

# Cargar variables desde .env (en la raíz del proyecto)
load_dotenv()


class Settings:
    """Configuración plana de la aplicación."""

    # Google Apps Script
    apps_script_url: str = os.getenv("APPS_SCRIPT_URL", "")
    apps_script_token: str = os.getenv("APPS_SCRIPT_TOKEN", "")

    # Google Sheets (fallback)
    google_credentials_json: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    sheet_id: str = os.getenv("SHEET_ID", "")
    sheet_name: str = os.getenv("SHEET_NAME", "")

    # Base de datos
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./auditoria.db")

    # Bootstrap Excel
    bootstrap_excel: str = os.getenv("BOOTSTRAP_EXCEL", "CAMIONES FIJOS NACIONAL HUEVO.xlsx")

    # Rate limiting
    rate_limit_max: int = int(os.getenv("RATE_LIMIT_MAX", "10"))
    rate_limit_window: int = int(os.getenv("RATE_LIMIT_WINDOW", "10"))

    # Reintentos
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    retry_base_delay: float = float(os.getenv("RETRY_BASE_DELAY", "1.0"))


settings = Settings()
