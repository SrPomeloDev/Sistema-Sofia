# Gestión de Camiones — Sofía Ltda / Nacional Huevo

Sistema web para la gestión integral de flota de camiones. Panel de control en tiempo real con KPIs, sincronización bidireccional con Google Sheets, autenticación local por usuario y exportación a Excel/CSV. Instalable como PWA en iOS y Android.

> Desarrollado como proyecto de pasantía por **Pablo Salomón Moya** — Área Servicio Logístico, Sofía Ltda.

---

## Stack Tecnológico

| Capa | Tecnología |
|------|-----------|
| Backend | **Python 3.14** — FastAPI + Uvicorn |
| ORM | **SQLAlchemy 2.x** asíncrono (aiosqlite) |
| Base de datos | **SQLite** (`auditoria.db`) |
| Frontend | **Vanilla JS** (sin frameworks) + Lucide icons |
| PWA | Service Worker + Manifest JSON |
| Sincronización | **Google Apps Script** (Web App puente hacia Google Sheets) |
| Autenticación | Login local con tokens en memoria (sin registro) |
| Exportación | Excel (openpyxl) y CSV nativo |
| Hosting | Railway (Nixpacks) — `uvicorn main:app --host 0.0.0.0 --port $PORT` |

---

## Origen del Proyecto

El sistema nació de la necesidad de **centralizar y digitalizar** el registro de camiones fijos de las tres sucursales (Santa Cruz, Cochabamba, La Paz). Antes se manejaban planillas Excel dispersas y archivos HTML exportados de Google Sheets sin un punto de control único.

Se construyó desde cero con los siguientes objetivos:
- Unificar ~400 registros de camiones en una sola base de datos SQLite.
- Permitir consulta y edición en tiempo real desde cualquier dispositivo.
- Mantener sincronización bidireccional con Google Sheets (planilla compartida).
- Proveer KPIs visuales por sucursal y estado de flota.
- Ser instalable como app en celulares del personal logístico.

---

## Estructura del Proyecto

```
CAMIONES/
│
├── main.py                          # Entrypoint FastAPI + lifespan + rutas PWA
├── railway.json                     # Config de deploy Railway (Nixpacks)
├── requirements.txt                 # Dependencias Python
├── .env                             # Variables de entorno (no commiteado)
├── .env.example                     # Plantilla para .env
│
├── modules/camiones/                # Módulo principal
│   ├── __init__.py                  # Exporta router, init_module, shutdown_module
│   ├── lifecycle.py                 # Startup lógica, push a sheets, auto-sync loop
│   ├── routes.py                    # APIRouter con todos los endpoints REST
│   ├── models.py                    # Schemas Pydantic v2 (request/response)
│   ├── config.py                    # Config desde .env con python-dotenv
│   ├── auth.py                      # Login local con tokens (2 usuarios)
│   ├── db/
│   │   └── database.py              # Modelos SQLAlchemy + CRUD asíncrono
│   └── services/
│       ├── sheets.py                # Cliente Google Sheets (httpx → Apps Script)
│       ├── queue.py                 # Cola asíncrona + TokenBucket rate limiter
│       └── excel_parser.py          # Parser de Excel para bootstrap inicial
│
├── static/
│   ├── index.html                   # Landing page (app móvil)
│   ├── manifest.json                # Manifiesto PWA
│   ├── sw.js                        # Service Worker (cache offline)
│   ├── icons/                       # Íconos PNG + SVG
│   ├── camiones/
│   │   ├── index.html               # Dashboard SPA (app shell)
│   │   └── login.html               # Pantalla de inicio de sesión
│
├── rebuild_db.py                    # Script admin: reconstruye DB desde Excel
├── Code.gs                          # Google Apps Script (v5.2, desplegado)
│
├── AGENTS.md                        # Notas internas para el agente de código
└── README.md                        # Este archivo
```

---

## Instalación y Ejecución Local

### 1. Clonar y crear entorno virtual

```bash
git clone <repo>
cd CAMIONES
python -m venv venv
```

### 2. Instalar dependencias

```bash
venv\Scripts\pip install -r requirements.txt
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env con la URL del Web App de Apps Script
```

### 4. Iniciar servidor

```bash
venv\Scripts\uvicorn main:app --reload --port 8000
```

Abrir [http://127.0.0.1:8000](http://127.0.0.1:8000) → Landing page.
Ir a `/camiones` → Dashboard (requiere login).

---

## Autenticación

El sistema usa login local con credenciales hardcodeadas en `auth.py`:

| Usuario | Contraseña | Nombre |
|---------|-----------|--------|
| `31100` | `7794890` | Augusto Admin |
| `12345678` | `13227173` | pablo admin |

Las sesiones duran 24 horas. No hay registro públicos.

---

## Funcionalidades

### Dashboard
- KPIs generales: total camiones, capacidad útil total, último cambio
- KPIs por sucursal (tarjetas dinámicas con conteo)
- Estado de flota: En Servicio / Fuera de Servicio / Consultar
- Tabla de datos con filtros por placa, sucursal, combustible, sistema y estado
- Carga progresiva (chunks de 50 registros)

### CRUD
- **Registrar** nuevo camión: auto-asigna Nº secuencial por sucursal, calcula capacidad útil (maples × 1.95) y factor 0.75
- **Editar**: modificar cualquier campo, recalcula valores automáticos
- **Eliminar**: borra localmente y en Sheets (reajusta fila_ids)

### Historial (Auditoría)
- Cada creación, modificación o eliminación se registra con timestamp (huso Bolivia UTC-4)
- Muestra quién hizo el cambio (nombre + email extraído de la sesión)
- Visible siempre en el dashboard, auto-refresh cada 10s

### Sincronización con Google Sheets
- Push local → Sheets (botón "Push"): escribe 11 columnas con 400 filas
- Sync Sheets → local (botón "Sync"): importa datos foráneos respetando duplicados
- Auto-sync cada 30s si local tiene menos registros que el sheet
- Cola asíncrona con TokenBucket (10 req/10s) y retry exponencial

### Exportación
- **CSV**: exporta datos filtrados con headers
- **Excel**: descarga .xlsx con formato profesional (encabezados azules, bordes)

### PWA (Progressive Web App)
- Instalable en Android (Chrome) e iOS (Safari)
- Service Worker con cache offline de la app shell
- Meta tags específicos para iOS (apple-touch-icon, mask-icon)

---

## API Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/login` | Iniciar sesión |
| `POST` | `/api/logout` | Cerrar sesión |
| `GET` | `/api/check-auth` | Verificar token |
| `GET` | `/api/status` | KPIs, modo, pendientes |
| `GET` | `/api/camiones` | Listar todos los camiones |
| `POST` | `/api/camiones` | Crear camión |
| `PUT` | `/api/camiones/{fila_id}` | Actualizar camión |
| `DELETE` | `/api/camiones/{fila_id}` | Eliminar camión |
| `GET` | `/api/camiones/export/xlsx` | Exportar Excel con filtros |
| `POST` | `/api/sync` | Forzar sync desde Sheets |
| `POST` | `/api/push-to-sheets` | Subir local → Sheets (background) |
| `GET` | `/api/push-status` | Estado de subida actual |
| `GET` | `/api/fletes` | Promedio flete por sucursal |
| `GET` | `/api/auditoria` | Historial de operaciones |
| `GET` | `/api/health` | Health check |

---

## Google Sheets / Apps Script

- **Sheet ID:** `1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw`
- **Hoja:** `Hoja1`
- **Token:** `pablo9090`
- **Code.gs v5.2** desplegado en `script.google.com`

Para reconectar:
1. Ir a [script.google.com](https://script.google.com)
2. Crear proyecto, pegar `Code.gs`
3. Desplegar → Web App → Ejecutar como "Yo" → Acceso "Cualquiera"
4. Copiar URL de implementación en `.env` como `APPS_SCRIPT_URL`

---

## Despliegue en Railway

1. Conectar repo de GitHub
2. En Railway dashboard, setear variable `APPS_SCRIPT_URL`
3. `railway.json` ya está configurado con Nixpacks
4. Railway ejecuta: `uvicorn main:app --host 0.0.0.0 --port $PORT`

El startup automático:
- DB vacía + sheet con datos → sync desde sheet
- DB vacía + sheet vacío → bootstrap desde Excel master
- DB con datos + sheet incompleto → push en background

---

## Reconstruir DB (Admin)

```bash
python rebuild_db.py
```

Lee los 4 archivos Excel (SCZ, LPZ, CBBA, FIJOS), mergea, deduplica por placa, asigna N° secuencial por sucursal y reconstruye `auditoria.db` con ~400 registros.

---

## Convenciones de Desarrollo

- Los schemas usan Pydantic v2 (`model_dump`, `exclude_unset`)
- La zona horaria por defecto es **Bolivia (UTC-4)**
- `modificado_por` se auto-completa desde la sesión; `modificado_por_email` lo ingresa el usuario
- `capacidad_util_kg` se recalcula como `maples × 1.95`
- La cola de sincronización nunca bloquea el request

---

## Licencia

Uso interno — Sofía Ltda. Proyecto de pasantía.
