# AGENTS.md — Sistema Integrado Nacional Huevo

## Run

```bash
cd C:\Users\lenov\Desktop\CAMIONES
update-sheet-app\venv\Scripts\uvicorn main:app --reload
```

O abrir http://127.0.0.1:8000. El menú principal lista los módulos disponibles.
Ir a `/camiones` para el dashboard de gestión de flota.

## Estructura modular

```
CAMIONES/
├── main.py                          # Entry point principal
├── modules/
│   └── camiones/                    # Módulo: Sistema de Camiones
│       ├── __init__.py              # Exporta router + init_module/shutdown_module
│       ├── routes.py                # APIRouter con todos los endpoints
│       ├── lifecycle.py             # init_db, sync, queue, auto_sync
│       ├── models.py                # Pydantic schemas
│       ├── config.py                # dotenv config
│       ├── db/database.py           # SQLite + CRUD
│       └── services/
│           ├── sheets.py            # Cliente Google Sheets (httpx)
│           ├── queue.py             # Cola asíncrona + rate limiter
│           └── excel_parser.py      # Parser Excel bootstrap
├── static/
│   ├── index.html                   # Landing page con menú de módulos
│   ├── manifest.json                # PWA manifest
│   ├── sw.js                        # Service Worker (offline cache)
│   ├── icons/                       # Iconos PWA (192px, 512px)
│   └── camiones/index.html          # Dashboard de camiones
├── update-sheet-app/                # Versión anterior (monolítica)
│   └── app/ (old structure)
├── .env                             # Variables de entorno
└── AGENTS.md
```

## Cómo agregar un nuevo módulo

1. Crear `modules/mi_modulo/` con `__init__.py`, `routes.py`, `lifecycle.py`
2. En `main.py`, importar y registrar:
   ```python
   from modules.mi_modulo import router, init_module, shutdown_module
   app.include_router(router)
   # En lifespan: await init_module() / await shutdown_module()
   ```
3. Agregar tarjeta en `static/index.html`

## Key facts

- **No pydantic-settings.** `config.py` usa `python-dotenv`.
- **No Alembic.** Schema changes require deleting `auditoria.db`.
- **Google Sheets** via Apps Script Web App con token `pablo9090`. Sheet ID `1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw`, Hoja `Hoja1`.
- **Auto-sync** cada 30s (Sheets → SQLite) + cola asíncrona para writes (Dashboard → Sheets).
- **Dedupe por placa** en `guardar_camiones_bulk` y `upsert_camiones_desde_sheets`.
- **Duplicado conocido** en Sheets: placa `4265-UYX` (se conserva la primera).
- **PWA** instalable: manifest.json + service worker con caché offline.

## Convention notes

- `add_middleware` debe usar la clase importada, no string path: `app.add_middleware(CORSMiddleware, ...)`
- `CamionUpdate` usa `exclude_unset=True`.
- Nº de tabla es contador por sucursal client-side, no el campo `nro` storeado.
- Sheets cleanup: `upsert_camiones_desde_sheets` ahora elimina registros `sincronizados` que ya no están en Sheets.
- Pending sync badge en botón Recargar se actualiza cada 10s desde `/api/status`.
