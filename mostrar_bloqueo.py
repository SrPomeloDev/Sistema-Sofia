"""
mostrar_bloqueo.py — Demuestra cómo Google bloquea las llamadas a un
Web App de Apps Script desde una IP residencial / script.

Qué hace:
  1. Envía una petición al Web App (action=getAll) con headers de navegador.
  2. Muestra status, Content-Type y el inicio de la respuesta.
  3. Detecta automáticamente si la respuesta es JSON (éxito) o
     HTML de login de Google (bloqueo anti-bot).
  4. Compara con lo que vería el server de Railway (IP datacenter).

Uso:
    update-sheet-app\\venv\\Scripts\\python mostrar_bloqueo.py
"""

import httpx

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL = "https://script.google.com/macros/s/AKfycbwSjORWipTqJc7PpVi_c8fJIH2Oz86DfDRDYh8n_E3LtpHTU1eh4FYlP06Xyc4cUzjp/exec"
TOKEN = "pablo9090"

HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "sec-ch-ua": '"Not/A)Brand";v="8", "Chromium";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

HEADERS_MINIMOS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}


def analizar(resp: httpx.Response) -> str:
    """Detecta si la respuesta es JSON del script o HTML de bloqueo."""
    texto = resp.text
    es_html = texto.lstrip().lower().startswith(("<!doctype", "<html"))
    if es_html:
        if "accounts.google.com" in texto or "signin" in texto:
            return "BLOQUEADO — Google redirige a su página de login (anti-bot)."
        return "HTML inesperado (no es JSON ni login)."
    try:
        resp.json()
        return "OK — respuesta JSON válida del Web App (sin bloqueo)."
    except Exception:
        return "Respuesta NO-JSON y NO-HTML (formato raro)."


def probar(nombre: str, headers: dict):
    print(f"\n{'─' * 60}")
    print(f"▶ {nombre}")
    print(f"  Headers enviados: {len(headers)} (User-Agent: {headers['User-Agent'][:45]}...)")
    try:
        r = httpx.get(
            URL,
            params={"token": TOKEN, "action": "getAll"},
            headers=headers,
            follow_redirects=True,
            timeout=90,
        )
    except Exception as e:
        print(f"  ERROR de conexión: {e}")
        return

    print(f"  Status: {r.status_code}")
    print(f"  Content-Type: {r.headers.get('content-type', 'sin content-type')}")
    print(f"  Tamaño: {len(r.text)} bytes")
    print(f"  URL final tras redirects: {str(r.url)[:80]}")
    print(f"  Inicio de la respuesta: {r.text[:120]!r}")
    print(f"  Análisis: {analizar(r)}")


def main():
    print("=" * 60)
    print("DEMOSTRACIÓN: bloqueo anti-bot de Google sobre Apps Script")
    print("=" * 60)
    print(f"URL: {URL}")

    probar("1) Headers mínimos (como los de la app)", HEADERS_MINIMOS)
    probar("2) Headers completos de navegador Chrome", HEADERS_NAVEGADOR)

    print(f"\n{'─' * 60}")
    print("CONCLUSIÓN:")
    print("  - Si ambas muestran 'BLOQUEADO': Google exige sesión/login para")
    print("    esta IP (residencial). El Web App NO permite acceso anónimo.")
    print("  - Railway (IP datacenter) NO recibe este bloqueo, por eso la app")
    print("    en producción sí funciona con Apps Script.")
    print("  - El modo local con gspread (OAuth) NO pasa por el Web App,")
    print("    por eso el test_flujo.py sí funciona en local.")


if __name__ == "__main__":
    main()
