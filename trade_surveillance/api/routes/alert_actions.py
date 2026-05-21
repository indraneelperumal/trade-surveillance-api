from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from trade_surveillance.auth import get_current_user
from trade_surveillance.crud import alerts as alerts_crud
from trade_surveillance.crud import investigations as investigations_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.models.user import User
from trade_surveillance.schemas.alerts import AlertRead
from trade_surveillance.schemas.cases import (
    ApproveInvestigationRequest,
    AssignAlertRequest,
    CloseAlertRequest,
    EscalateAlertRequest,
)
from trade_surveillance.schemas.common import ErrorResponse
from trade_surveillance.services import alert_workflow

router = APIRouter(prefix="/alerts")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def _get_alert_or_404(db: Session, alert_id: UUID):
    alert = alerts_crud.get_alert(db, alert_id)
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


@router.post("/{alert_id}/assign", response_model=AlertRead, responses=ERROR_RESPONSES)
def assign_alert(
    alert_id: UUID,
    payload: AssignAlertRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AlertRead:
    alert = _get_alert_or_404(db, alert_id)
    try:
        return alert_workflow.assign_alert(
            db, alert, assigned_to=payload.assigned_to, actor=current_user
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{alert_id}/take", response_model=AlertRead, responses=ERROR_RESPONSES)
def take_alert(
    alert_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AlertRead:
    alert = _get_alert_or_404(db, alert_id)
    return alert_workflow.take_alert(db, alert, current_user)


@router.post("/{alert_id}/escalate", response_model=AlertRead, responses=ERROR_RESPONSES)
def escalate_alert(
    alert_id: UUID,
    payload: EscalateAlertRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AlertRead:
    alert = _get_alert_or_404(db, alert_id)
    try:
        return alert_workflow.escalate_alert(db, alert, current_user, payload.note)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{alert_id}/close", response_model=AlertRead, responses=ERROR_RESPONSES)
def close_alert(
    alert_id: UUID,
    payload: CloseAlertRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> AlertRead:
    alert = _get_alert_or_404(db, alert_id)
    try:
        return alert_workflow.close_alert(
            db,
            alert,
            current_user,
            disposition=payload.disposition,
            note=payload.note,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post(
    "/{alert_id}/investigation/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERROR_RESPONSES,
)
def approve_alert_investigation(
    alert_id: UUID,
    payload: ApproveInvestigationRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> None:
    invs = investigations_crud.list_investigations(db, offset=0, limit=1, alert_id=alert_id)
    if not invs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No investigation for this case.",
        )
    try:
        alert_workflow.approve_investigation(
            db,
            invs[0].id,
            current_user,
            override_note=payload.override_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
