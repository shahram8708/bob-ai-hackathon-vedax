from datetime import timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.models.base import utcnow

ALGORITHM = "HS256"
SESSION_COOKIE = "chargeopt_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> tuple[str, int]:
    settings = get_settings()
    ttl = settings.jwt_expire_minutes * 60
    now = utcnow()
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": now + timedelta(seconds=ttl), "typ": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM), ttl


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload if payload.get("typ") == "access" else None
