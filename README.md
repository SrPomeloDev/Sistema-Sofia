# Gestión de Camiones — Nacional Huevo / Sofía Ltda

Sistema web para la gestión de flota de camiones con panel de control en tiempo real, sincronización bidireccional con Google Sheets y exportación a Excel/CSV.

## Stack

- **Backend**: FastAPI (Python 3.14) + SQLAlchemy async + aiosqlite
- **Frontend**: Vanilla JS (sin framework) + Lucide icons + PWA (manifest + service worker)
- **Base de datos**: SQLite (`auditoria.db`)
- **Sincronización**: Google Apps Script Web App (puente hacia Google Sheets)
- **Hosting**: Local (uvicorn)

## Requisitos

- Python 3.14+
- Entorno virtual en `update-sheet-app/venv/`

## Instalación

```bash
update-sheet-app\venv\Scripts\pip install fastapi uvicorn httpx python-dotenv sqlalchemy aiosqlite openpyxl
```

## Uso

```bash
update-sheet-app\venv\Scripts\uvicorn main:app --reload --port 8000
```

Abrir http://127.0.0.1:8000. Ir a `/camiones` para el dashboard.

## Estructura

```
main.py                          # Entry point FastAPI
├── modules/camiones/            # Módulo principal
│   ├── routes.py                # Endpoints REST
│   ├── lifecycle.py             # Init/shutdown, auto-sync cada 30s
│   ├── models.py                # Schemas Pydantic
│   ├── config.py                # Config desde .env (python-dotenv)
│   ├── db/database.py           # Modelos SQLAlchemy + CRUD
│   └── services/
│       ├── sheets.py            # Cliente Google Sheets (httpx + Apps Script)
│       ├── queue.py             # Cola asíncrona con rate limiter
│       └── excel_parser.py      # Parser Excel para bootstrap
├── static/camiones/index.html   # Dashboard SPA
├── static/manifest.json         # PWA manifest
├── static/sw.js                 # Service Worker
├── Code.gs                      # Apps Script (desplegar en script.google.com)
├── .env                         # Variables de entorno (token, URLs)
└── AGENTS.md                    # Notas para el agente de código
```

## Funcionalidades

- CRUD completo de camiones (alta, baja, modificación)
- Dashboard con KPIs (total, capacidad, por sucursal, estado de flota)
- Filtros por placa, sucursal, combustible, sistema y estado
- Sincronización automática con Google Sheets cada 30 segundos
- Exportación a Excel (con filtros activos) y CSV
- Panel de auditoría con historial de operaciones
- Instalable como PWA (offline cache)
- Exportación de reporte de fletes por sucursal

## Google Sheets

La app se sincroniza con una planilla de Google Sheets vía un Web App de Apps Script. Para configurar:

1. Copiar `Code.gs` a script.google.com
2. Desplegar como Web App (ejecutar como "Yo", acceso "Cualquiera")
3. Copiar la URL de implementación en `.env` como `APPS_SCRIPT_URL`
4. El token `APPS_SCRIPT_TOKEN` debe coincidir con `API_TOKEN` en `Code.gs`

## Endpoints principales

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/camiones` | Listar todos los camiones |
| POST | `/api/camiones` | Crear camión |
| PUT | `/api/camiones/{fila_id}` | Actualizar camión |
| DELETE | `/api/camiones/{fila_id}` | Eliminar camión (sheet + DB) |
| GET | `/api/camiones/export/xlsx` | Exportar Excel (con filtros) |
| POST | `/api/sync` | Forzar sincronización desde Sheets |
| GET | `/api/status` | Estado de sincronización |
| GET | `/api/fletes` | Promedio de flete por sucursal |
| GET | `/api/auditoria` | Historial de operaciones |
