# AGENTS.md — Sistema Nacional Huevo (Camiones)

## Run

```bash
cd C:\Users\lenov\Desktop\CAMIONES
update-sheet-app\venv\Scripts\uvicorn main:app --reload
```

Abrir http://127.0.0.1:8000 → landing page. `/camiones` → dashboard.

## Estructura

```
CAMIONES/
├── main.py                          # Entrypoint FastAPI + lifespan app
├── modules/camiones/
│   ├── __init__.py                  # Exporta router, init_module, shutdown_module
│   ├── lifecycle.py                 # Startup logic, push, sync, auto_sync loop
│   ├── routes.py                    # APIRouter (todos los endpoints)
│   ├── models.py                    # Pydantic v2 schemas
│   ├── config.py                    # python-dotenv (NO pydantic-settings)
│   ├── db/database.py               # SQLAlchemy async + SQLite CRUD
│   └── services/
│       ├── sheets.py                # Cliente Google Sheets (httpx → Apps Script)
│       ├── queue.py                 # Cola async + TokenBucket rate limiter
│       └── excel_parser.py          # Bootstrap Excel (34 rec master file)
├── static/camiones/index.html       # Dashboard SPA (2494 lines, vanilla JS)
├── static/{index.html,manifest.json,sw.js,icons/}
├── Code.gs                          # Google Apps Script (v5.2, desplegado)
├── rebuild_db.py                    # Admin: rebuild DB from 4 Excel files → 400 rec
├── railway.json                     # Nixpacks, start: uvicorn main:app --host 0.0.0.0 --port $PORT
├── requirements.txt                 # fastapi, uvicorn, pydantic, httpx, sqlalchemy[asyncio], aiosqlite
└── .env                             # No commited. APPS_SCRIPT_URL + token
```

## Startup logic (`lifecycle.py:init_module`)

1. `init_db()` — crea tablas si no existen
2. `sheets_client.initialize()` — conecta Apps Script
3. **Local vacío + sheet con datos** → sync desde sheets (Railway)
4. **Local vacío + sheet vacío** → bootstrap desde Excel (solo 34 rec, master file)
5. **Local con datos + sheet tiene menos** → push local → sheets en background
6. **Local con datos + sheet tiene más** → sync desde sheets
7. Arranca `update_queue.start()` + `auto_sync_loop()`

## Auto-sync (cada 30s)

Solo sincroniza si `local_count < sheet_count`. Si local ya tiene >= que el sheet, salta. Esto evita que datos corruptos del sheet sobrescriban datos limpios locales.

## Push a Sheets

- **No hace `clear_sheet`** — nunca borra el sheet antes de escribir
- Primero intenta `setAll` (1 request, overwrite completo con headers + 400 filas)
- Fallback: update fila por fila, batches de 10 concurrentes
- Push envía **11 columnas** (incluye `estado_servicio` en col K)

## Google Sheets / Apps Script

- **Sheet ID:** `1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw` — Hoja `Hoja1`
- **Token:** `pablo9090`
- **Code.gs v5.2** desplegado en `script.google.com`
- **detectFormat:** mira col D (header index 3). Si es `"Ruta"` → formato legacy 11-col (con espacio), sino → formato 10-col estándar. Nuestro `HEADERS_LIST` tiene `"Tipo de combustible"` en D → fmt=10.
- `HEADERS_LIST` (`sheets.py:17-29`): 11 items, col K = `"Estado Servicio"`
- `actionSetAll` recibe `{headers, data}` y escribe todo el sheet (headers + filas) en 1 llamada

## Railway

- `railway.json`: Nixpacks builder, `uvicorn main:app --host 0.0.0.0 --port $PORT`
- `requirements.txt` tiene todas las deps
- `.env` NO se commitea. **Variable `APPS_SCRIPT_URL` debe setearse en Railway dashboard**
- Los Excel de ciudades (SCZ, LPZ, CBBA) están en `.gitignore` — solo existe el master Excel (~34 rec)
- Si sheet tiene datos ≥ 1, Railway arranca sync desde sheet (no usa Excel). Solo si sheet vacío hace bootstrap del master Excel.

## Endpoints clave (desde dashboard)

| Ruta                        | Método | Uso                             |
| --------------------------- | ------- | ------------------------------- |
| `/api/camiones`           | GET     | Lista todos                     |
| `/api/camiones`           | POST    | Crear (11 vals, encola append)  |
| `/api/camiones/{fila_id}` | PUT     | Editar (11 vals, encola update) |
| `/api/camiones/{fila_id}` | DELETE  | Eliminar + shift fila_ids       |
| `/api/sync`               | POST    | Forzar sync desde sheets        |
| `/api/push-to-sheets`     | POST    | Push local→sheets (background) |
| `/api/push-status`        | GET     | Estado del push actual          |
| `/api/status`             | GET     | KPIs, counts, pending sync      |
| `/api/fletes`             | GET     | Promedio flete por sucursal     |

## Convenciones

- `HEADERS` en `routes.py` (10 items, sin Estado Servicio) no se usa — es código muerto. El real es `HEADERS_LIST` en `sheets.py`.
- `CamionUpdate` usa `exclude_unset=True` — solo envía campos modificados
- `add_middleware(CORSMiddleware, ...)` con clase importada, no string
- `capacidad_util_kg` recalcula como `maples * 1.95` al crear/editar
- Nº de tabla es contador por sucursal, se recalcula y persiste en DB durante push
- Dedup por placa en `guardar_camiones_bulk` y `upsert_camiones_desde_sheets`
- Schema changes: delete `auditoria.db` (no Alembic)
- Push badge se actualiza cada 10s desde `/api/status`
- Cola async con TokenBucket (10 req/10s default), retry exponencial (3 intentos)

## Nuevo módulo

1. Crear `modules/mi_modulo/` con `__init__.py`, `routes.py`, `lifecycle.py`
2. En `main.py`:
   ```python
   from modules.mi_modulo import router, init_module, shutdown_module
   app.include_router(router)
   # En lifespan: await init_module() / await shutdown_module()
   ```
3. Agregar tarjeta en `static/index.html`

## Rebuild DB (admin)

```bash
update-sheet-app\venv\Scripts\python rebuild_db.py
```

Lee los 4 Excel (SCZ, LPZ, CBBA, FIJOS), mergea, deduplica, asigna nros secuenciales por sucursal, y reconstruye `auditoria.db` con 400 registros. Los Excel están en `.gitignore` — no se sincronizan a Railway.
