# AGENTS.md — Nacional Huevo (Camiones + Rutas)

## Run

```bash
cd C:\Users\lenov\Desktop\CAMIONES
update-sheet-app\venv\Scripts\uvicorn main:app --reload
```

Abrir http://127.0.0.1:8000. `/camiones` → dashboard, `/rutas` → dashboard.

## No tests / lint / typecheck

Solo `python -m py_compile` para verificar compilación. No ejecutar pytest, ruff, mypy.

## Auth

`modules/camiones/auth.py` — dos usuarios hardcodeados: `31100`/`7794890` ("Augusto Admin"), `12345678`/`13227173` ("pablo admin"). Login `POST /api/login` con JSON `{"username","password"}`. Retorna token. Sesiones en memoria, expiran 24h. Todos los endpoints mutantes requieren `?token=...`.

Frontends guardan `localStorage.auth_token`. Errores del backend se muestran con `d.detail || d.message`.

## Arquitectura

FastAPI, dos módulos montados en `main.py:39-40`.

| Módulo | Init | Tablas |
|--------|------|--------|
| `modules/camiones/` | `lifecycle.py:init_module` → init_db, poblar ruta_madre, sync desde sheets/boot desde Excel, push manual | `camiones` + `auditoria` + `rutas_tarifas` |
| `modules/rutas/` | `lifecycle.py:init_module` → init_db, seed desde Excel si vacío | `rutas_madre` + `rutas_hijas` |

DB única: `auditoria.db` (SQLite, `sqlite+aiosqlite:///./auditoria.db`). Ambos módulos comparten engine.

**Auto-sync NO activo.** `auto_sync_loop` está definido pero nunca se inicia (vía `init_module`). Solo existe push manual (botón en dashboard o `POST /api/push-to-sheets`).

### Cross-module

`modules/camiones/db/database.py:569` importa `RutaMadreDb` y `async_session_factory` desde `modules/rutas/db/database.py`:

- `poblar_ruta_madre_desde_ruta()` (line 567): deduce `ruta_madre` desde `ruta` consultando `rutas_madre.nombre`
- `asignar_rutas_desde_madres()` (line 595): reverse — asigna `ruta` desde `ruta_madre` ("local" si madre = "MERCADO")
- `obtener_flete_por_ruta_o_madre()` (`rutas/db/database.py:298`): busca `flete` en `rutas_hijas`; usado para `flete_proyectado` en dashboard

## Google Sheets

`.env` configura **gspread con OAuth 2.0** (`GOOGLE_OAUTH_CLIENT_SECRET`). El Web App de Apps Script (`Code.gs`) es fallback.

`Code.gs` desplegado como Web App. `SPREADSHEET_ID` hardcodeado. `API_TOKEN = ""` (vacío en el archivo; se define al desplegar o via `.env`).

**Acciones:** `getAll`, `getRow`, `append`, `update`, `clear`, `writeHeaders`. Formato fijo de 10 columnas (A-J). No hay `detectFormat`, `setAll`, `ensureRutaColumn`.

**Push local → sheets** escribe 11 columnas (A-K: incluye "Estado Servicio" col K). `HEADERS_LIST` en `sheets.py:17`.

## Endpoints

### /api/rutas

| Ruta | Método | Auth | Notas |
|------|--------|------|-------|
| `/madres` | GET | No | `?sucursal=` para filtrar |
| `/madres` | POST | Sí | `(sucursal, nombre)`. 409 si UniqueConstraint violado |
| `/madres/{id}` | PUT | Sí | Renombrar |
| `/madres/{id}` | DELETE | Sí | Cascade elimina hijas |
| `/hijas` | POST | Sí | `(ruta_madre_id, ruta_hija, flete, metodo)` |
| `/hijas/{id}` | PUT | Sí | `exclude_unset=True` — solo campos enviados |
| `/hijas/{id}` | DELETE | Sí | |
| `/seed` | POST | Sí+confirm | Solo si tabla vacía |
| `/reseed` | POST | Sí+confirm | Limpia + seed completo |

Seed/reseed requieren `?confirm=true` además de `?token=`.

### /api/camiones

| Ruta | Método | Notas |
|------|--------|-------|
| `/camiones` | GET | Lista con `flete_proyectado` desde rutas |
| `/camiones` | POST | Crea local + encola sync a sheets; auto-asigna N° por sucursal, calcula `capacidad_util_kg = maples * 1.95` |
| `/camiones/{fila_id}` | PUT | Partial update (`exclude_unset=True`); recalcula `capacidad_util_kg` si maples cambió |
| `/camiones/{fila_id}` | DELETE | Borra sheets por placa, reajusta fila_ids, luego borra local |
| `/sync` | POST | Pull sheets → local (upsert) |
| `/push-to-sheets` | POST | Push local → sheets en background |
| `/push-status` | GET | Estado del push actual |
| `/fletes/rutas` | GET | RutaTarifa paginado (`?offset=&limit=`) |
| `/fletes/ruta` | POST | Crear tarifa (409 si duplicada) |
| `/fletes/ruta` | PUT | Crear o actualizar tarifa |
| `/fletes/ruta/{ruta}` | DELETE | Eliminar tarifa |
| `/fletes` | GET | Promedio flete por sucursal |
| `/fletes/promedios-por-ruta` | GET | Promedio por ruta_madre, opcional `?sucursal=` |
| `/fletes/costos-por-ruta` | GET | Costos por ruta hija |
| `/fletes/poblar-ruta-madre` | POST | Deduce `ruta_madre` desde `ruta` para todos |
| `/fletes/asignar-rutas` | POST | Reverse: asigna `ruta` desde `ruta_madre` |
| `/fletes/seed-planilla` | POST | Parsea `PLANILLA DE MÉTODOS PARA PAGOS.xlsx` |
| `/auditoria` | GET | Historial (`?limit=20`) |
| `/status` | GET | KPIs, modo, pendientes |
| `/camiones/export/xlsx` | GET | Exporta filtrado a Excel |
| `/health` | GET | Health check |
| `/bootstrap` | POST | Mergea HTMLs legacy a sheets |
| `/login` / `/logout` / `/check-auth` | POST/GET | Auth |

## Seed de Rutas desde Excel

`BBDDs_SL.xlsx` hoja `RUTAS` (155 filas: SUCURSAL, Ruta Madre, Ruta Hija, Flete, Método, Observación). `_parse_float_safe()` (`rutas/db/database.py:75`) maneja comas decimales. `metodo` con solo whitespace → `None`. `_resolve_seed_path()` busca en 3 ubicaciones.

## Convenciones importantes

- `exclude_unset=True` en PUTs (tanto camiones como rutas hijas)
- `ON DELETE CASCADE` en FK `rutas_hijas.ruta_madre_id`
- `UniqueConstraint("sucursal", "nombre")` en `rutas_madre` → 409 si duplicado
- `PRAGMA foreign_keys=ON` en `init_db()` de rutas (SQLite no lo activa por defecto)
- `flete` es `Float` en SQLAlchemy, no Decimal
- `capacidad_util_kg = maples * 1.95`
- `formatPrice(val)` en frontends: muestra enteros sin decimales, solo `.XX` si hay parte fraccionaria
- `estado_sincronizacion` por defecto `"sincronizado"`; errores en columna separada

## Railway deploy

`railway.json` usa Nixpacks. Comando: `uvicorn main:app --host 0.0.0.0 --port $PORT`. Variable requerida: `APPS_SCRIPT_URL` (o `GOOGLE_OAUTH_CLIENT_SECRET`).

## Rebuild DB

```bash
update-sheet-app\venv\Scripts\python rebuild_db.py
```
