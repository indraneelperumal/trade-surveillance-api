from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.crud import alerts as alerts_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.alerts import AlertCreate, AlertRead, AlertUpdate
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse

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
def create_alert(payload: AlertCreate, db: Session = Depends(get_db_session)) -> AlertRead:
    return alerts_crud.create_alert(db, payload)


@router.get("", response_model=PaginatedResponse[AlertRead], responses=ERROR_RESPONSES)
def list_alerts(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[AlertRead]:
    items = alerts_crud.list_alerts(db, offset=offset, limit=limit)
    total = alerts_crud.count_alerts(db)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{alert_id}", response_model=AlertRead, responses=ERROR_RESPONSES)
def get_alert(alert_id: UUID, db: Session = Depends(get_db_session)) -> AlertRead:
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.patch("/{alert_id}", response_model=AlertRead, responses=ERROR_RESPONSES)
def update_alert(
    alert_id: UUID,
    payload: AlertUpdate,
    db: Session = Depends(get_db_session),
) -> AlertRead:
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alerts_crud.update_alert(db, alert, payload)


@router.delete(
    "/{alert_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_alert(alert_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    alerts_crud.delete_alert(db, alert)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
