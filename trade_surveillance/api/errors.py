from __future__ import annotations

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from trade_surveillance.schemas.common import ErrorResponse


def _error_payload(code: str, message: str, details: object | None = None) -> dict:
    return ErrorResponse.model_validate(
        {"error": {"code": code, "message": message, "details": details}}
    ).model_dump()


async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(code=str(exc.status_code), message=detail),
    )


async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            code="422",
            message="Validation failed",
            details=exc.errors(),
        ),
    )


async def unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=_error_payload(code="500", message="Internal server error", details=str(exc)),
    )
