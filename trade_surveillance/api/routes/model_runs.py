from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.crud import model_runs as model_runs_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse
from trade_surveillance.schemas.model_runs import ModelRunCreate, ModelRunRead, ModelRunUpdate

router = APIRouter(prefix="/model-runs")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=ModelRunRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_model_run(payload: ModelRunCreate, db: Session = Depends(get_db_session)) -> ModelRunRead:
    return model_runs_crud.create_model_run(db, payload)


@router.get("", response_model=PaginatedResponse[ModelRunRead], responses=ERROR_RESPONSES)
def list_model_runs(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[ModelRunRead]:
    items = model_runs_crud.list_model_runs(db, offset=offset, limit=limit)
    total = model_runs_crud.count_model_runs(db)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{model_run_id}", response_model=ModelRunRead, responses=ERROR_RESPONSES)
def get_model_run(model_run_id: UUID, db: Session = Depends(get_db_session)) -> ModelRunRead:
    model_run = model_runs_crud.get_model_run(db, model_run_id)
    if not model_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model run not found")
    return model_run


@router.patch("/{model_run_id}", response_model=ModelRunRead, responses=ERROR_RESPONSES)
def update_model_run(
    model_run_id: UUID,
    payload: ModelRunUpdate,
    db: Session = Depends(get_db_session),
) -> ModelRunRead:
    model_run = model_runs_crud.get_model_run(db, model_run_id)
    if not model_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model run not found")
    return model_runs_crud.update_model_run(db, model_run, payload)


@router.delete(
    "/{model_run_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_model_run(model_run_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    model_run = model_runs_crud.get_model_run(db, model_run_id)
    if not model_run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model run not found")
    model_runs_crud.delete_model_run(db, model_run)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
