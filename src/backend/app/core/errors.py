import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("chargeopt.errors")


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | list | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(entity: str) -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, "not_found", f"{entity} not found")


def conflict(message: str, details: dict | None = None) -> AppError:
    return AppError(status.HTTP_409_CONFLICT, "conflict", message, details)


def bad_request(message: str, details: dict | None = None) -> AppError:
    return AppError(status.HTTP_400_BAD_REQUEST, "invalid_request", message, details)


def forbidden(message: str = "You do not have permission to perform this action") -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)), headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        issues = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(_body("validation_error", "Some fields are invalid", issues)),
        )

    @app.exception_handler(ValidationError)
    async def _model_error(_: Request, exc: ValidationError):
        issues = [{"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]} for err in exc.errors()]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(_body("validation_error", "Some settings are invalid", issues)),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity_error(_: Request, exc: IntegrityError):
        log.warning("Integrity error: %s", exc.orig)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_body("conflict", "The change conflicts with existing data (duplicate or invalid reference)"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body("internal_error", "An unexpected error occurred. The incident has been logged."),
        )
