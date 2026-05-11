from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.auth import get_current_user
from trade_surveillance.crud import alerts as alerts_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.models.user import User
from trade_surveillance.schemas.alerts import AlertCreate, AlertRead, AlertUpdate
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse

_RESTRICTED_STATUSES = {"CLOSED", "ESCALATED"}

router = APIRouter(prefix="/alerts")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=AlertRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_alert(
    payload: AlertCreate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AlertRead:
    if payload.status and payload.status.upper() in _RESTRICTED_STATUSES:
        if current_user.role != "COMPLIANCE_LEAD":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Creating an alert with status '{payload.status}' requires the "
                    "COMPLIANCE_LEAD role."
                ),
            )
    return alerts_crud.create_alert(db, payload)


@router.get("", response_model=PaginatedResponse[AlertRead], responses=ERROR_RESPONSES)
def list_alerts(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = None,
    severity: str | None = None,
    symbol: str | None = None,
    anomaly_type: str | None = Query(default=None, alias="anomalyType"),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[AlertRead]:
    items = alerts_crud.list_alerts(
        db,
        offset=offset,
        limit=limit,
        status=status,
        severity=severity,
        symbol=symbol,
        anomaly_type=anomaly_type,
    )
    total = alerts_crud.count_alerts(
        db,
        status=status,
        severity=severity,
        symbol=symbol,
        anomaly_type=anomaly_type,
    )
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{alert_id}", response_model=AlertRead, responses=ERROR_RESPONSES)
def get_alert(alert_id: UUID, db: Session = Depends(get_db_session)) -> AlertRead:
    alert = alerts_crud.get_alert_read(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.patch("/{alert_id}", response_model=AlertRead, responses=ERROR_RESPONSES)
def update_alert(
    alert_id: UUID,
    payload: AlertUpdate,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AlertRead:
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    # Only COMPLIANCE_LEAD may close or escalate an alert.
    if payload.status and payload.status.upper() in _RESTRICTED_STATUSES:
        if current_user.role != "COMPLIANCE_LEAD":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Setting status to '{payload.status}' requires the COMPLIANCE_LEAD role. "
                    "Contact your compliance lead to close or escalate this alert."
                ),
            )
        # Disposition is required when closing.
        if payload.status.upper() == "CLOSED" and not payload.disposition:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A disposition is required when closing an alert.",
            )
        # Server-stamp reviewer + review time via model_copy so Pydantic v2
        # includes them in model_dump(exclude_unset=True) — direct attribute
        # assignment after construction does not update __pydantic_fields_set__.
        payload = payload.model_copy(
            update={
                "reviewed_by": current_user.id,
                "reviewed_at": datetime.now(timezone.utc),
            }
        )

    return alerts_crud.update_alert(db, alert, payload)


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_alert(
    alert_id: UUID,
    db: Session = Depends(get_db_session),
    _: User = Depends(get_current_user),
) -> Response:
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alerts_crud.delete_alert(db, alert)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
