from collections.abc import Callable

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from app.core.errors import AppError, forbidden, not_found
from app.core.permissions import Perm, permissions_for
from app.core.security import SESSION_COOKIE, decode_access_token
from app.db.session import get_db
from app.models import User


def token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get(SESSION_COOKIE)


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    payload = decode_access_token(token)
    if payload is None:
        return None
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, token_from_request(request))
    if user is None:
        raise AppError(status.HTTP_401_UNAUTHORIZED, "unauthorized", "Authentication required")
    request.state.user = user
    return user


def require(*perms: Perm) -> Callable[..., User]:
    def checker(user: User = Depends(current_user)) -> User:
        granted = permissions_for(user.role_code)
        if not any(p in granted for p in perms):
            raise forbidden()
        return user

    return checker


def has_perm(user: User, perm: Perm) -> bool:
    return perm in permissions_for(user.role_code)


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_or_404(db: Session, model, ident: int, label: str):
    obj = db.get(model, ident)
    if obj is None:
        raise not_found(label)
    return obj
