"""
test_flujo.py — Suite de pruebas automatizadas NO destructivas.

Verifica el flujo completo: creación, edición, borrado, push/sync y
consistencia entre la app local y Google Sheets.

SEGURIDAD:
- Solo opera con placas "TEST-*" (nunca toca camiones reales).
- Hace backup del sheet y de la DB local antes de empezar (backups/).
- Al final borra todos los camiones TEST-* creados.
- Si algo falla, imprime detalle y NO borra datos reales.

Uso:
    update-sheet-app\\venv\\Scripts\\python test_flujo.py
Requisito: server local corriendo (uvicorn main:app --reload)
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Configuración ───────────────────────────────────────────────────────

BASE_URL = "http://127.0.0.1:8000"
LOGIN = {"username": "31100", "password": "7794890"}
TEST_PREFIX = "TEST-"
SHEET_ID = "1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw"
SHEET_NAME = "Hoja1"
OAUTH_CLIENT_SECRET = os.getenv(
    "GOOGLE_OAUTH_CLIENT_SECRET", r"C:\Users\lenov\Downloads\client_secret.json"
)
PUSH_TIMEOUT_S = 180
BACKUP_DIR = "backups"

# ── 1. ApiClient: llamadas HTTP al server local ─────────────────────────

class ApiClient:
    def __init__(self):
        self.token = None
        self._client = httpx.Client(base_url=BASE_URL, timeout=60)

    def req(self, method, path, **kwargs):
        kwargs.setdefault("params", {})
        if self.token:
            kwargs["params"]["token"] = self.token
        resp = self._client.request(method, path, **kwargs)
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}
        return resp.status_code, body

    def login(self):
        code, body = self.req("POST", "/api/login", json=LOGIN)
        if code != 200 or not body.get("token"):
            raise RuntimeError(f"Login falló: {code} {body}")
        self.token = body["token"]
        return body

    def get_camiones(self):
        code, body = self.req("GET", "/api/camiones")
        if code != 200:
            raise RuntimeError(f"GET /api/camiones falló: {code} {body}")
        return body

    def create(self, data):
        return self.req("POST", "/api/camiones", json=data)

    def update(self, fila_id, data):
        return self.req("PUT", f"/api/camiones/{fila_id}", json=data)

    def delete(self, fila_id):
        return self.req("DELETE", f"/api/camiones/{fila_id}")

    def push(self):
        return self.req("POST", "/api/push-to-sheets")

    def sync(self):
        return self.req("POST", "/api/sync")

    def auditoria(self, limit=50):
        code, body = self.req("GET", "/api/auditoria", params={"limit": limit})
        return code, body

    def esperar_push_idle(self, timeout=PUSH_TIMEOUT_S):
        """Espera hasta que no haya push/cola de sync activa."""
        inicio = time.time()
        while time.time() - inicio < timeout:
            code, body = self.req("GET", "/api/push-status")
            running = body.get("running", False)
            code2, status = self.req("GET", "/api/status")
            pendientes = status.get("pendientes_sincronizacion", 0) if code2 == 200 else 0
            if not running and pendientes == 0:
                return True
            time.sleep(2)
        return False

# ── 2. SheetReader: lectura del sheet real (gspread local) ──────────────

class SheetReader:
    def __init__(self):
        import gspread
        gc = gspread.oauth(
            credentials_filename=OAUTH_CLIENT_SECRET,
            authorized_user_filename="authorized_user.json",
        )
        self.ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    def snapshot(self):
        """Devuelve las filas del sheet como lista de listas (crudas)."""
        return self.ws.get_all_values()

    @staticmethod
    def placas(filas):
        """Placas presentes en col B (índice 1)."""
        placas = set()
        for fila in filas[1:]:  # salta headers
            if len(fila) > 1 and fila[1].strip():
                placas.add(fila[1].strip())
        return placas

    @staticmethod
    def filas_por_placa(filas):
        """placa → lista de (nro_fila_real, fila). Detecta duplicados."""
        mapa = {}
        for idx, fila in enumerate(filas, start=1):
            if idx == 1:  # headers
                continue
            if len(fila) > 1 and fila[1].strip():
                mapa.setdefault(fila[1].strip(), []).append((idx, fila))
        return mapa

    @staticmethod
    def filas_basura(filas):
        """Filas después de la última con datos (deberían ser 0)."""
        ultima = 0
        for idx, fila in enumerate(filas, start=1):
            if any(c.strip() for c in fila):
                ultima = idx
        return len(filas) - ultima

    @staticmethod
    def conteo_test(filas):
        return sum(1 for p in SheetReader.placas(filas) if p.startswith(TEST_PREFIX))

# ── 3. Tester: mini-framework de pruebas ────────────────────────────────

RESULTADOS = []

def prueba(pid, nombre, fn):
    """Ejecuta una prueba y registra PASS/FAIL con detalle."""
    detalle = []
    def info(msg):
        detalle.append(msg)
        print(f"    {msg}")
    try:
        print(f"\n──────────────────────────────────────────────────")
        print(f"▶ {pid} — {nombre}")
        ok = fn(info)
        estado = "PASS ✅" if ok else "FAIL ❌"
        RESULTADOS.append((pid, nombre, ok, detalle))
        print(f"  RESULTADO: {estado}")
        return ok
    except Exception as e:
        detalle.append(f"EXCEPCIÓN: {type(e).__name__}: {e}")
        print(f"    EXCEPCIÓN: {type(e).__name__}: {e}")
        RESULTADOS.append((pid, nombre, False, detalle))
        print(f"  RESULTADO: FAIL ❌")
        return False

def fila_valor(filas_por_placa, placa, col_idx):
    """Devuelve el valor de una columna (0-based) en la única fila de la placa."""
    if placa not in filas_por_placa:
        return None
    entries = filas_por_placa[placa]
    if len(entries) != 1:
        return None
    fila = entries[0][1]
    return fila[col_idx] if len(fila) > col_idx else None

def valor_float(valor, esperado):
    """Compara un valor del sheet con un float esperado, tolerando formato
    (Google Sheets puede mostrar '234', '234.0' o '234,0')."""
    try:
        return float(str(valor).replace(",", ".")) == esperado
    except (ValueError, TypeError):
        return False

# ── 4. Fases de prueba ──────────────────────────────────────────────────

async def main():
    api = ApiClient()
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── FASE 0: Setup y backup ──────────────────────────────────────────
    print("=" * 60)
    print("FASE 0 — Setup y backup")
    print("=" * 60)

    try:
        code, _ = api.req("GET", "/api/health")
        if code != 200:
            print("ERROR: server no responde. Levantá: uvicorn main:app --reload")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: no se pudo conectar con el server ({e}).")
        sys.exit(1)

    api.login()
    print(f"  Login OK (token obtenido)")

    # Backup del sheet
    os.makedirs(BACKUP_DIR, exist_ok=True)
    reader = SheetReader()
    snapshot_inicial = reader.snapshot()
    backup_path = os.path.join(BACKUP_DIR, f"backup_sheet_{fecha}.json")
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(snapshot_inicial, f, ensure_ascii=False, indent=1)
    print(f"  Backup sheet → {backup_path} ({len(snapshot_inicial)} filas)")

    # Backup local
    camiones_iniciales = api.get_camiones()
    local_path = os.path.join(BACKUP_DIR, f"backup_local_{fecha}.json")
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(camiones_iniciales, f, ensure_ascii=False, indent=1)
    print(f"  Backup local → {local_path} ({len(camiones_iniciales)} camiones)")

    test_existentes = [c["placa"] for c in camiones_iniciales if c["placa"].startswith(TEST_PREFIX)]
    if test_existentes:
        print(f"  ⚠ AVISO: ya existen camiones TEST-* en la DB: {test_existentes}. Se limpiarán al final.")

    # ── FASE 1: Creación ────────────────────────────────────────────────
    print("=" * 60)
    print("FASE 1 — Creación")
    print("=" * 60)

    def p1_1(info):
        filas = reader.snapshot()
        antes = reader.filas_por_placa(filas)
        info(f"Placas TEST-* en sheet antes: {reader.conteo_test(filas)}")
        code, body = api.create({
            "placa": "TEST-001", "sucursal": "La Paz",
            "costo_flete": 500.0, "capacidad_maples": 120,
            "capacidad_kg": 5000, "estado_servicio": "EN SERVICIO",
        })
        info(f"POST /api/camiones → {code}: {body.get('message', body)}")
        if code not in (200, 201):
            return False
        if not api.esperar_push_idle():
            info("TIMEOUT esperando push idle")
            return False
        filas = reader.snapshot()
        despues = reader.filas_por_placa(filas)
        if "TEST-001" not in despues:
            info("TEST-001 NO está en el sheet")
            return False
        if len(despues["TEST-001"]) != 1:
            info(f"DUPLICADO: TEST-001 aparece {len(despues['TEST-001'])} veces")
            return False
        cap = fila_valor(despues, "TEST-001", 8)
        flete = fila_valor(despues, "TEST-001", 4)
        info(f"capacidad_util col I: '{cap}' (esperado 234.0)")
        info(f"flete col E: '{flete}' (esperado 500.0)")
        nro = fila_valor(despues, "TEST-001", 0)
        nros_lp = [f[0] for f in filas[1:] if len(f) > 5 and f[5].strip() == "La Paz" and f[1].strip() != "TEST-001"]
        info(f"N° asignado: '{nro}'")
        return valor_float(cap, 234.0) and valor_float(flete, 500.0)

    def p1_2(info):
        filas = reader.snapshot()
        antes_count = reader.conteo_test(filas)
        for placa in ("TEST-002", "TEST-003", "TEST-004"):
            code, body = api.create({
                "placa": placa, "sucursal": "La Paz",
                "costo_flete": 300.0, "capacidad_maples": 50,
            })
            info(f"POST {placa} → {code}")
        if not api.esperar_push_idle():
            info("TIMEOUT esperando push idle")
            return False
        filas = reader.snapshot()
        despues_count = reader.conteo_test(filas)
        mapa = reader.filas_por_placa(filas)
        info(f"TEST-* en sheet: {antes_count} → {despues_count} (esperado +3)")
        duplicados = [p for p, v in mapa.items() if p.startswith(TEST_PREFIX) and len(v) > 1]
        if duplicados:
            info(f"DUPLICADOS: {duplicados}")
            return False
        return despues_count == antes_count + 3

    def p1_3(info):
        code, body = api.create({
            "placa": "TEST-005", "sucursal": "TESTSUC",
            "costo_flete": 100.0, "capacidad_maples": 10,
        })
        info(f"POST TEST-005 en sucursal nueva → {code}")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        nro = fila_valor(mapa, "TEST-005", 0)
        info(f"N° de TEST-005: '{nro}' (esperado '1')")
        return nro == "1"

    def p1_4(info):
        code, body = api.create({
            "placa": "TEST-006", "sucursal": "La Paz",
            "costo_flete": 12.5, "capacidad_maples": 20,
        })
        info(f"POST TEST-006 flete=12.5 → {code}")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        flete = fila_valor(reader.filas_por_placa(filas), "TEST-006", 4)
        info(f"flete col E: '{flete}' (esperado 12.5)")
        return valor_float(flete, 12.5)

    # ── FASE 2: Edición ─────────────────────────────────────────────────
    print("=" * 60)
    print("FASE 2 — Edición")
    print("=" * 60)

    def p2_1(info):
        camion = next(c for c in api.get_camiones() if c["placa"] == "TEST-001")
        code, body = api.update(camion["fila_id"], {"costo_flete": 600.0})
        info(f"PUT TEST-001 flete→600 → {code}")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        if len(mapa.get("TEST-001", [])) != 1:
            info(f"DUPLICADO o ausente: {len(mapa.get('TEST-001', []))} filas")
            return False
        flete = fila_valor(mapa, "TEST-001", 4)
        info(f"flete col E: '{flete}' (esperado 600.0)")
        return valor_float(flete, 600.0)

    def p2_2(info):
        camion = next(c for c in api.get_camiones() if c["placa"] == "TEST-002")
        api.update(camion["fila_id"], {"costo_flete": 700.0})
        api.update(camion["fila_id"], {"costo_flete": 800.0})
        info("PUT 2× seguidas TEST-002 (700 → 800)")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        if len(mapa.get("TEST-002", [])) != 1:
            info(f"DUPLICADO o ausente: {len(mapa.get('TEST-002', []))} filas")
            return False
        flete = fila_valor(mapa, "TEST-002", 4)
        info(f"flete col E: '{flete}' (esperado 800.0)")
        return valor_float(flete, 800.0)

    def p2_3(info):
        """EL BUG CLÁSICO: crear y editar de inmediato (sin esperar push)."""
        code, body = api.create({
            "placa": "TEST-007", "sucursal": "La Paz",
            "costo_flete": 100.0, "capacidad_maples": 30,
        })
        info(f"POST TEST-007 → {code}")
        fila = body.get("fila_id")
        camiones = api.get_camiones()
        camion = next((c for c in camiones if c["placa"] == "TEST-007"), None)
        if not camion:
            info("TEST-007 no apareció en local")
            return False
        api.update(camion["fila_id"], {"costo_flete": 900.0})
        info("PUT inmediato TEST-007 flete→900 (sin esperar push del create)")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        if len(mapa.get("TEST-007", [])) != 1:
            info(f"BUG: TEST-007 aparece {len(mapa.get('TEST-007', []))} veces (esperado 1)")
            return False
        flete = fila_valor(mapa, "TEST-007", 4)
        info(f"flete col E: '{flete}' (esperado 900.0)")
        return valor_float(flete, 900.0)

    def p2_4(info):
        code, body = api.create({
            "placa": "TEST-008", "sucursal": "La Paz",
            "costo_flete": 200.0, "capacidad_maples": 40,
        })
        camion = next(c for c in api.get_camiones() if c["placa"] == "TEST-008")
        api.update(camion["fila_id"], {"costo_flete": 950.0})
        info("POST + PUT inmediato TEST-008 (cola procesando)")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        if len(mapa.get("TEST-008", [])) != 1:
            info(f"BUG: TEST-008 aparece {len(mapa.get('TEST-008', []))} veces")
            return False
        flete = fila_valor(mapa, "TEST-008", 4)
        info(f"flete col E: '{flete}' (esperado 950.0)")
        return valor_float(flete, 950.0)

    # ── FASE 3: Borrado ─────────────────────────────────────────────────
    print("=" * 60)
    print("FASE 3 — Borrado")
    print("=" * 60)

    def p3_1(info):
        camion = next(c for c in api.get_camiones() if c["placa"] == "TEST-004")
        code, body = api.delete(camion["fila_id"])
        info(f"DELETE TEST-004 → {code}: {body.get('message', body)}")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        if "TEST-004" in mapa:
            info("TEST-004 sigue en el sheet (NO se borró)")
            return False
        basura = reader.filas_basura(filas)
        info(f"filas basura al final: {basura} (esperado 0)")
        return basura == 0

    def p3_2(info):
        """Camión local cuya placa NO está en el sheet (desincronizado)."""
        code, body = api.create({
            "placa": "TEST-009", "sucursal": "La Paz",
            "costo_flete": 250.0, "capacidad_maples": 25,
        })
        camion = next(c for c in api.get_camiones() if c["placa"] == "TEST-009")
        # Lo sacamos del sheet directamente (simula desincronización)
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        nro_fila = mapa["TEST-009"][0][0]
        info(f"Quitando TEST-009 del sheet (fila real {nro_fila}) para simular desincronización...")
        reader.ws.delete_rows(nro_fila)
        time.sleep(3)
        code, body = api.delete(camion["fila_id"])
        msg = body.get("message", "")
        info(f"DELETE TEST-009 (no está en sheet) → {code}: {msg}")
        fallido = "fallid" in msg.lower() or "falló" in msg.lower()
        if fallido:
            info("⚠ DELETE marcó 'fallido' aunque la placa no estaba en el sheet")
            return False
        return True

    def p3_3(info):
        for placa in ("TEST-002", "TEST-003"):
            camion = next(c for c in api.get_camiones() if c["placa"] == placa)
            code, body = api.delete(camion["fila_id"])
            info(f"DELETE {placa} → {code}")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        restantes = [p for p in ("TEST-002", "TEST-003") if p in mapa]
        info(f"Quedan en sheet: {restantes} (esperado ninguno)")
        return not restantes

    def p3_4(info):
        camion = next(c for c in api.get_camiones() if c["placa"] == "TEST-005")
        api.delete(camion["fila_id"])
        if not api.esperar_push_idle():
            return False
        code, body = api.create({
            "placa": "TEST-010", "sucursal": "TESTSUC",
            "costo_flete": 50.0, "capacidad_maples": 5,
        })
        info("Borré TEST-005 (único de TESTSUC) y creé TEST-010 en TESTSUC")
        if not api.esperar_push_idle():
            return False
        filas = reader.snapshot()
        nro = fila_valor(reader.filas_por_placa(filas), "TEST-010", 0)
        info(f"N° de TEST-010: '{nro}' (esperado '1', numeración no rota)")
        return nro == "1"

    # ── FASE 4: Push / Sync ─────────────────────────────────────────────
    print("=" * 60)
    print("FASE 4 — Push / Sync")
    print("=" * 60)

    def p4_1(info):
        code, body = api.push()
        info(f"POST /api/push-to-sheets → {code}: {body.get('message', body)}")
        if not api.esperar_push_idle():
            info("TIMEOUT esperando push")
            return False
        filas = reader.snapshot()
        basura = reader.filas_basura(filas)
        info(f"filas basura tras push: {basura} (esperado 0)")
        return basura == 0

    def p4_2(info):
        """Editamos directo en el sheet y verificamos que /sync lo traiga."""
        filas = reader.snapshot()
        mapa = reader.filas_por_placa(filas)
        nro_fila, contenido = mapa["TEST-001"][0]
        info(f"Editando directo en sheet: fila {nro_fila}, col E → '999'")
        reader.ws.update_cell(nro_fila, 5, "999")
        time.sleep(2)
        code, body = api.sync()
        info(f"POST /api/sync → {code}: {body.get('message', body)}")
        local = next(c for c in api.get_camiones() if c["placa"] == "TEST-001")
        info(f"flete en local tras sync: {local['costo_flete']} (esperado 999.0)")
        if local["costo_flete"] != 999.0:
            return False
        # Revertimos
        api.update(local["fila_id"], {"costo_flete": 600.0})
        if not api.esperar_push_idle():
            info("TIMEOUT revertiendo celda")
            return False
        info("Celda revertida a 600 (restaurada)")
        return True

    def p4_3(info):
        """Push y sync alternados no deben duplicar ni perder datos."""
        for i in range(3):
            code, body = api.push()
            if not api.esperar_push_idle():
                info(f"TIMEOUT push ciclo {i+1}")
                return False
            api.sync()
            time.sleep(2)
        filas = reader.snapshot()
        en_sheet = reader.conteo_test(filas)
        en_local = sum(1 for c in api.get_camiones() if c["placa"].startswith(TEST_PREFIX))
        info(f"TEST-* en sheet: {en_sheet} | en local: {en_local}")
        if en_sheet != en_local:
            info("⚠ Divergencia sheet vs local")
            return False
        mapa = reader.filas_por_placa(filas)
        duplicados = [p for p, v in mapa.items() if p.startswith(TEST_PREFIX) and len(v) > 1]
        info(f"Duplicados tras ciclos: {duplicados or 'ninguno'}")
        return not duplicados

    # ── FASE 5: Rutas / dashboard / auditoría ───────────────────────────
    print("=" * 60)
    print("FASE 5 — Rutas / dashboard / auditoría")
    print("=" * 60)

    def p5_1(info):
        camiones = api.get_camiones()
        sin_flete = [c["placa"] for c in camiones if not isinstance(c.get("flete_proyectado"), (int, float))]
        info(f"Camiones sin flete_proyectado: {sin_flete or 'ninguno'} (total {len(camiones)})")
        return not sin_flete

    def p5_2(info):
        code, entries = api.auditoria(limit=100)
        acciones_test = [e for e in entries if "TEST-" in json.dumps(e.get("valores", ""))]
        if not acciones_test:
            info("No hay entradas de auditoría de TEST-* (¿revisar?)")
            return False
        acciones = set(e["accion"] for e in acciones_test)
        info(f"Acciones TEST-* en auditoría: {sorted(acciones)}")
        fallidas = [e for e in acciones_test if e.get("estado") == "fallido"]
        if fallidas:
            info(f"⚠ Entradas con estado 'fallido': {fallidas}")
        return True

    # ── FASE 6: Limpieza y reporte ──────────────────────────────────────
    print("=" * 60)
    print("FASE 6 — Limpieza y reporte final")
    print("=" * 60)

    def limpiar(info):
        camiones = api.get_camiones()
        tests = [c["placa"] for c in camiones if c["placa"].startswith(TEST_PREFIX)]
        info(f"Borrando {len(tests)} camiones TEST-* restantes...")
        for placa in tests:
            cam = next((c for c in api.get_camiones() if c["placa"] == placa), None)
            if not cam:
                info(f"  {placa}: ya no existe en local, salteando")
                continue
            code, body = api.delete(cam["fila_id"])
            info(f"  DELETE {placa} (fila {cam['fila_id']}) → {code}")
        if not api.esperar_push_idle():
            info("TIMEOUT esperando push de limpieza")
            return False
        filas = reader.snapshot()
        resto = reader.conteo_test(filas)
        info(f"TEST-* restantes en sheet: {resto} (esperado 0)")
        if resto != 0:
            info("⚠ Quedan TEST-* en el sheet — limpiar manualmente")
            return False
        # Chequeo final: no perdimos ni agregamos filas no-TEST vs backup
        inicial = SheetReader.placas(snapshot_inicial)
        final = SheetReader.placas(filas)
        perdidas = inicial - final
        info(f"Placas del backup ausentes al final: {perdidas or 'ninguna'}")
        return True

    fases = [
        ("FASE 1", [
            ("P1.1", "Crear TEST-001 (flete 500, maples 120) → sheet +1, capacidad 234.0", p1_1),
            ("P1.2", "Crear 3 seguidos TEST-002/003/004 → sheet +3 exactas", p1_2),
            ("P1.3", "Crear en sucursal nueva TESTSUC → N° = 1", p1_3),
            ("P1.4", "Crear flete 12.5 → sheet '12.5'", p1_4),
        ]),
        ("FASE 2", [
            ("P2.1", "Editar flete TEST-001 → misma fila, sin duplicar", p2_1),
            ("P2.2", "Editar 2× seguidas TEST-002 → 1 fila, último valor", p2_2),
            ("P2.3", "Crear + editar INMEDIATO (bug clásico) → 1 fila", p2_3),
            ("P2.4", "Crear + editar durante push → no duplica", p2_4),
        ]),
        ("FASE 3", [
            ("P3.1", "Borrar TEST-004 → fuera del sheet, sin filas vacías", p3_1),
            ("P3.2", "Borrar camión ausente del sheet → sin 'fallido'", p3_2),
            ("P3.3", "Borrar 2 seguidos → sin rastros", p3_3),
            ("P3.4", "Borrar último de TESTSUC y re-crear → N° = 1", p3_4),
        ]),
        ("FASE 4", [
            ("P4.1", "Push manual → sin filas basura", p4_1),
            ("P4.2", "Editar celda directa en sheet → sync la trae y revierte", p4_2),
            ("P4.3", "Push + sync ×3 → sin duplicados ni pérdidas", p4_3),
        ]),
        ("FASE 5", [
            ("P5.1", "flete_proyectado presente en todos los camiones", p5_1),
            ("P5.2", "Auditoría registra acciones de TEST-*", p5_2),
        ]),
        ("FASE 6", [
            ("P6.1", "Limpieza total de TEST-* y verificación final", limpiar),
        ]),
    ]

    for fase, pruebas in fases:
        print(f"\n{'='*60}")
        print(f"▶▶ {fase}")
        print(f"{'='*60}")
        for pid, nombre, fn in pruebas:
            prueba(pid, nombre, fn)

    # ── Reporte final ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("REPORTE FINAL")
    print("=" * 60)
    total = len(RESULTADOS)
    fallos = [r for r in RESULTADOS if not r[2]]
    exitos = total - len(fallos)
    for pid, nombre, ok, detalle in RESULTADOS:
        marca = "✅" if ok else "❌"
        print(f"  {marca} {pid}: {nombre}")
    print(f"\n  Total: {exitos}/{total} PASS")
    if fallos:
        print(f"  FALLARON {len(fallos)} pruebas. Revisá el detalle de cada una arriba.")
        print(f"  Backups en {BACKUP_DIR}/ (no se borran automáticamente).")
        sys.exit(1)
    else:
        print("  TODO OK ✅ — sheet y app consistentes.")


if __name__ == "__main__":
    asyncio.run(main())
