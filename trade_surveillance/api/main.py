from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from trade_surveillance.api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from trade_surveillance.api.router import api_router
from trade_surveillance.config import get_settings
from trade_surveillance.db.migrator import create_tables_and_migrate

settings = get_settings()

app = FastAPI(
    title="Trade Surveillance API",
    version="0.1.0",
    description="Backend APIs for trade surveillance MVP.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.on_event("startup")
def startup_tasks() -> None:
    if settings.auto_migrate_on_startup:
        create_tables_and_migrate()


@app.get("/health")
def health_root() -> dict[str, str]:
    return {"status": "ok", "service": "trade-surveillance-api"}


app.include_router(api_router)
