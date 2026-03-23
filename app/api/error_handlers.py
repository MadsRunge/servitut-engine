from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger

logger = get_logger(__name__)

ERROR_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_server_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


def _default_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


def _normalize_http_detail(detail: Any, status_code: int) -> tuple[str, Any | None]:
    if isinstance(detail, str):
        return detail, None

    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message.strip():
            return message, detail

    return _default_message(status_code), detail


def build_error_payload(
    *,
    status_code: int,
    message: str,
    path: str,
    details: Any | None = None,
) -> dict[str, Any]:
    error = {
        "code": ERROR_CODES.get(status_code, "request_failed"),
        "message": message,
    }
    if details is not None:
        error["details"] = details

    return {
        "error": error,
        "path": path,
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        message, details = _normalize_http_detail(exc.detail, exc.status_code)
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_payload(
                status_code=exc.status_code,
                message=message,
                details=details,
                path=request.url.path,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=build_error_payload(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                message="Request validation failed",
                details=exc.errors(),
                path=request.url.path,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=build_error_payload(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Internal server error",
                path=request.url.path,
            ),
        )
