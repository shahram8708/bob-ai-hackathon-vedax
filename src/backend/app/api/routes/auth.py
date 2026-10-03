import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, token_from_request, user_from_token
from app.api.serializers import user_out
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import SESSION_COOKIE, create_access_token, verify_password
from app.db.session import get_db
from app.models import User
from app.schemas.operations import LoginIn
from app.services import audit
from app.services.config_service import now

router = APIRouter(prefix="/auth", tags=["auth"])

MAX_FAILURES = 5
WINDOW_SECONDS = 300
_failures: dict[str, deque] = defaultdict(deque)
_lock = Lock()


def _throttled(key: str) -> bool:
    with _lock:
        q = _failures[key]
        cutoff = time.monotonic() - WINDOW_SECONDS
        while q and q[0] < cutoff:
            q.popleft()
        return len(q) >= MAX_FAILURES


def _fail(key: str) -> None:
    with _lock:
        _failures[key].append(time.monotonic())


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    ip = client_ip(request)
    key = f"{body.email}|{ip}"
    if _throttled(key):
        raise AppError(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts", "Too many failed sign-in attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        _fail(key)
        audit.record(db, actor=None, actor_label=body.email, action="auth.login_failed", category="auth", summary=f"Failed sign-in for {body.email}", ip_address=ip)
        db.commit()
        raise AppError(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Email or password is incorrect")
    with _lock:
        _failures.pop(key, None)
    token, ttl = create_access_token(user.id, user.role_code)
    user.last_login_at = now()
    audit.record(db, actor=user, action="auth.login", category="auth", summary=f"{user.full_name} signed in", entity_type="user", entity_id=user.id, ip_address=ip)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="strict",
        path="/",
    )
    return {"user": user_out(user), "expires_in": ttl}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    user = user_from_token(db, token_from_request(request))
    if user is not None:
        audit.record(db, actor=user, action="auth.logout", category="auth", summary=f"{user.full_name} signed out", entity_type="user", entity_id=user.id, ip_address=client_ip(request))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/session")
def session(request: Request, db: Session = Depends(get_db)):
    user = user_from_token(db, token_from_request(request))
    return {"user": user_out(user) if user else None}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)
