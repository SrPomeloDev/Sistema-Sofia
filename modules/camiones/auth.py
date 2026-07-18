"""
auth.py — Login local con credenciales predefinidas. Sin registro.
"""

import secrets
from datetime import datetime, timedelta

# ── Editar aquí los usuarios y contraseñas ──────────────────────
# Formato: "usuario": ("contraseña", "Nombre visible")
USERS = {
    "31100":    ("7794890", "Augusto Admin"),
    "12345678": ("13227173", "pablo admin"),
}
# ────────────────────────────────────────────────────────────────

_sessions: dict[str, dict] = {}
TOKEN_EXPIRE_HOURS = 24

def verify_credentials(username: str, password: str) -> bool:
    if username not in USERS:
        return False
    return USERS[username][0] == password

def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    name = USERS[username][1] if username in USERS else username
    _sessions[token] = {
        "username": username,
        "display_name": name,
        "created_at": datetime.utcnow(),
    }
    return token

def verify_session(token: str) -> dict | None:
    session = _sessions.get(token)
    if not session:
        return None
    elapsed = datetime.utcnow() - session["created_at"]
    if elapsed > timedelta(hours=TOKEN_EXPIRE_HOURS):
        del _sessions[token]
        return None
    return session

def destroy_session(token: str):
    _sessions.pop(token, None)
