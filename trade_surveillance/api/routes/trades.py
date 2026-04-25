from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.crud import trades as trades_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse
from trade_surveillance.schemas.trades import TradeCreate, TradeRead, TradeUpdate

router = APIRouter(prefix="/trades")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=TradeRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_trade(payload: TradeCreate, db: Session = Depends(get_db_session)) -> TradeRead:
    return trades_crud.create_trade(db, payload)


@router.get("", response_model=PaginatedResponse[TradeRead], responses=ERROR_RESPONSES)
def list_trades(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    symbol: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[TradeRead]:
    items = trades_crud.list_trades(db, offset=offset, limit=limit, symbol=symbol)
    total = trades_crud.count_trades(db, symbol=symbol)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{trade_id}", response_model=TradeRead, responses=ERROR_RESPONSES)
def get_trade(trade_id: UUID, db: Session = Depends(get_db_session)) -> TradeRead:
    trade = trades_crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return trade


@router.patch("/{trade_id}", response_model=TradeRead, responses=ERROR_RESPONSES)
def update_trade(
    trade_id: UUID,
    payload: TradeUpdate,
    db: Session = Depends(get_db_session),
) -> TradeRead:
    trade = trades_crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    return trades_crud.update_trade(db, trade, payload)


@router.delete(
    "/{trade_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_trade(trade_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    trade = trades_crud.get_trade(db, trade_id)
    if not trade:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trade not found")
    trades_crud.delete_trade(db, trade)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
