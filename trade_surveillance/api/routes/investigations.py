from __future__ import annotations

import os
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.agents.orchestrator import investigate_trade
from trade_surveillance.crud import alerts as alerts_crud
from trade_surveillance.crud import investigations as investigations_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse
from trade_surveillance.schemas.investigations import (
    InvestigationCreate,
    InvestigationRead,
    InvestigationUpdate,
)

router = APIRouter(prefix="/investigations")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}

# Severities that the agent will investigate. LOW and NONE are excluded to
# avoid burning API credits on statistically marginal signals.
_INVESTIGABLE_SEVERITIES = {"HIGH", "MEDIUM"}


@router.post(
    "/run/{alert_id}",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Trigger AI investigation for an alert",
    description=(
        "Enqueues a LangGraph compliance investigation for the given alert. "
        "Returns 202 immediately — the agent runs asynchronously. "
        "Poll GET /investigations?alert_id={id} for the result."
    ),
)
def trigger_investigation(
    alert_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db_session),
) -> dict:
    # Guard 1 — API key must be present before we accept the request.
    # Fail fast here rather than 10 seconds into the background task.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "ANTHROPIC_API_KEY is not configured on this server. "
                "Add it to the Render environment variables."
            ),
        )

    # Guard 2 — Alert must exist.
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert {alert_id} not found.",
        )

    # Guard 3 — Prevent a second agent run while one is already in progress.
    if alert.status == "IN_PROGRESS":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "An investigation is already in progress for this alert. "
                "Poll GET /investigations?alert_id={} for the result.".format(alert_id)
            ),
        )

    # Guard 4 — Only investigate HIGH and MEDIUM severity alerts.
    if (alert.severity or "").upper() not in _INVESTIGABLE_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Alert severity is '{alert.severity}'. "
                "AI investigations are reserved for HIGH and MEDIUM severity alerts."
            ),
        )

    # All guards passed — fire the agent in the background and return 202.
    # The orchestrator writes the investigation row and sets alert→IN_PROGRESS
    # atomically when it completes.
    background_tasks.add_task(investigate_trade, str(alert_id))

    return {
        "status": "queued",
        "alert_id": str(alert_id),
        "severity": alert.severity,
        "message": (
            f"Investigation started for alert {alert_id}. "
            f"Poll GET /api/v1/investigations?alert_id={alert_id} for the result."
        ),
    }


@router.post(
    "",
    response_model=InvestigationRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_investigation(
    payload: InvestigationCreate,
    db: Session = Depends(get_db_session),
) -> InvestigationRead:
    return investigations_crud.create_investigation(db, payload)


@router.get("", response_model=PaginatedResponse[InvestigationRead], responses=ERROR_RESPONSES)
def list_investigations(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    alert_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[InvestigationRead]:
    items = investigations_crud.list_investigations(
        db,
        offset=offset,
        limit=limit,
        alert_id=alert_id,
    )
    total = investigations_crud.count_investigations(db, alert_id=alert_id)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{investigation_id}", response_model=InvestigationRead, responses=ERROR_RESPONSES)
def get_investigation(investigation_id: UUID, db: Session = Depends(get_db_session)) -> InvestigationRead:
    record = investigations_crud.get_investigation(db, investigation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    return record


@router.patch("/{investigation_id}", response_model=InvestigationRead, responses=ERROR_RESPONSES)
def update_investigation(
    investigation_id: UUID,
    payload: InvestigationUpdate,
    db: Session = Depends(get_db_session),
) -> InvestigationRead:
    record = investigations_crud.get_investigation(db, investigation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    return investigations_crud.update_investigation(db, record, payload)


@router.delete(
    "/{investigation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_investigation(investigation_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    record = investigations_crud.get_investigation(db, investigation_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found")
    investigations_crud.delete_investigation(db, record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
