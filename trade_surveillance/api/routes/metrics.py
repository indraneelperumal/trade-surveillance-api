from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trade_surveillance.crud import metrics as metrics_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse
from trade_surveillance.schemas.metrics import OverviewMetricsRead

router = APIRouter(prefix="/metrics")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.get("/overview", response_model=OverviewMetricsRead, responses=ERROR_RESPONSES)
def overview_metrics(db: Session = Depends(get_db_session)) -> OverviewMetricsRead:
    return metrics_crud.get_overview_metrics(db)
