from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from trade_surveillance.crud import users as users_crud
from trade_surveillance.db.session import get_db_session
from trade_surveillance.schemas.common import ErrorResponse, PaginatedResponse
from trade_surveillance.schemas.users import UserCreate, UserRead, UserUpdate

router = APIRouter(prefix="/users")
ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses=ERROR_RESPONSES,
)
def create_user(payload: UserCreate, db: Session = Depends(get_db_session)) -> UserRead:
    return users_crud.create_user(db, payload)


@router.get("", response_model=PaginatedResponse[UserRead], responses=ERROR_RESPONSES)
def list_users(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> PaginatedResponse[UserRead]:
    items = users_crud.list_users(db, offset=offset, limit=limit)
    total = users_crud.count_users(db)
    return PaginatedResponse(items=items, total=total, offset=offset, limit=limit)


@router.get("/{user_id}", response_model=UserRead, responses=ERROR_RESPONSES)
def get_user(user_id: UUID, db: Session = Depends(get_db_session)) -> UserRead:
    user = users_crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserRead, responses=ERROR_RESPONSES)
def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db_session),
) -> UserRead:
    user = users_crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return users_crud.update_user(db, user, payload)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=ERROR_RESPONSES,
)
def delete_user(user_id: UUID, db: Session = Depends(get_db_session)) -> Response:
    user = users_crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    users_crud.delete_user(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
