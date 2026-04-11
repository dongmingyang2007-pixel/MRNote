from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id,
        },
        "detail": message,
    }
    retry_after = (details or {}).get("retry_after")
    if retry_after is not None:
        payload["retry_after"] = retry_after
    return JSONResponse(
        status_code=status_code,
        content=payload,
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        code="http_error",
        message=str(exc.detail),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    sanitized_errors = [
        {
            "loc": error.get("loc", []),
            "msg": error.get("msg", "Invalid value"),
            "type": error.get("type", "validation_error"),
        }
        for error in exc.errors()
    ]
    return build_error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed",
        details={"errors": sanitized_errors},
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
    import logging
    logging.getLogger(__name__).exception("Unhandled error on %s %s", request.method, request.url.path)
    return build_error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Internal server error",
    )
