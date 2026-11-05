import uuid

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user, current_user_id
from app.services import transfers

# main.py의 기존 router 등록을 그대로 사용하고 두 리소스를 같은 모듈에 둔다.
router = APIRouter(tags=["transfers"])


class TransferIn(BaseModel):
    from_account_id: uuid.UUID
    to_account_num: str = Field(pattern=r"^[0-9]{3}-[0-9]{4}-[0-9]{4}$")
    amount: int = Field(gt=0, strict=True)
    memo: str | None = Field(default=None, max_length=100)
    pin: str = Field(pattern=r"^[0-9]{6}$")
    idempotency_key: str = Field(min_length=8, max_length=58)  # user:{UUID}: 접두사 포함 DB 최대 100자


class AliasIn(BaseModel):
    alias: str | None = Field(default=None, max_length=50)


class FavoriteIn(AliasIn):
    account_num: str = Field(pattern=r"^[0-9]{3}-[0-9]{4}-[0-9]{4}$")


@router.get("/transfers/recipient")
def check_recipient(account_num: str = Query(pattern=r"^[0-9]{3}-[0-9]{4}-[0-9]{4}$"),
                    user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return transfers.check_recipient(db, user_id, account_num)


@router.post("/transfers", status_code=201)
def create_transfer(body: TransferIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return transfers.create_transfer(db, user, **body.model_dump())


@router.get("/transfers/by-key/{idempotency_key}")
def get_result(idempotency_key: str = Path(min_length=8, max_length=58),
               user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return transfers.get_by_key(db, user_id, idempotency_key)


@router.get("/transfers/recent")
def recent(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return transfers.recent_recipients(db, user_id)


@router.get("/favorite-recipients")
def favorites(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return transfers.list_favorites(db, user_id)


@router.post("/favorite-recipients", status_code=201)
def add_favorite(body: FavoriteIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return transfers.add_favorite(db, user_id, **body.model_dump())


@router.patch("/favorite-recipients/{item_id}")
def update_favorite(item_id: int, body: AliasIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return transfers.update_favorite(db, user_id, item_id, body.alias)


@router.delete("/favorite-recipients/{item_id}", status_code=204)
def delete_favorite(item_id: int, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    transfers.delete_favorite(db, user_id, item_id)
    return Response(status_code=204)
