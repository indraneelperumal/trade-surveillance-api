from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from trade_surveillance.auth import get_current_user
from trade_surveillance.db.session import get_db_session
from trade_surveillance.models.user import User
from trade_surveillance.schemas.cases import CaseBundleRead
from trade_surveillance.schemas.common import ErrorResponse
from trade_surveillance.services.case_bundle import get_case_bundle

router = APIRouter(prefix="/cases")
ERROR_RESPONSES = {404: {"model": ErrorResponse}}


@router.get("/{alert_id}", response_model=CaseBundleRead, responses=ERROR_RESPONSES)
def get_case(
    alert_id: UUID,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> CaseBundleRead:
    bundle = get_case_bundle(db, alert_id, current_user)
    if not bundle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    return bundle
