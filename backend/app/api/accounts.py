import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user, current_user_id, verify_pin
from app.services import accounts

router = APIRouter(tags=["accounts"])


class OpenAccountIn(BaseModel):
    product_code: str = Field(default="basic", max_length=20)
    password: str = Field(pattern=r"^[0-9]{4}$")
    password_confirm: str = Field(pattern=r"^[0-9]{4}$")
    opening_info: dict
    nickname: str | None = Field(default=None, max_length=50)
    agreed_term_ids: list[int]


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{6}$")


class LimitsIn(PinIn):
    daily_limit: int = Field(strict=True)
    month_limit: int = Field(strict=True)


class UnlockIn(BaseModel):
    code: str = Field(pattern=r"^[0-9]{6}$")


class StatementIn(BaseModel):
    from_date: date
    to_date: date
    email: EmailStr


class VerifyPinIn(PinIn):
    account_id: uuid.UUID | None = None


@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    return accounts.list_products(db)


@router.get("/accounts")
def list_accounts(status: Literal["active", "closed"] = "active",
                  user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.list_accounts(db, user_id, status)


@router.post("/accounts", status_code=201)
def open_account(body: OpenAccountIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.open_account(db, user_id, **body.model_dump())


@router.get("/accounts/{account_id}")
def get_account(account_id: uuid.UUID, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.get_account(db, user_id, account_id)


@router.get("/accounts/{account_id}/transactions")
def list_transactions(
    account_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    direction: Literal["IN", "OUT", "ALL"] = "ALL",
    order: Literal["desc", "asc"] = "desc",
    transaction_type: Literal["DEPOSIT", "WITHDRAW", "TRANSFER", "AUTO_TRANSFER", "CARD"] | None = Query(default=None, alias="type"),
    min_amount: int | None = Query(default=None, ge=0, alias="min"),
    max_amount: int | None = Query(default=None, ge=0, alias="max"),
    amount: int | None = Query(default=None, ge=0),
    q: str | None = Query(default=None, max_length=100),
    user_id: uuid.UUID = Depends(current_user_id),
    db: Session = Depends(get_db),
):
    return accounts.list_transactions(db, user_id, account_id, start=from_date or start, end=to_date or end,
        direction=direction, order=order, transaction_type=transaction_type,
        min_amount=min_amount, max_amount=max_amount, amount=amount, q=q)


@router.get("/accounts/{account_id}/transactions/{tx_id}")
def get_transaction(account_id: uuid.UUID, tx_id: int, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.get_transaction(db, user_id, account_id, tx_id)


@router.post("/accounts/{account_id}/favorite")
def toggle_favorite(account_id: uuid.UUID, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.toggle_favorite(db, user_id, account_id)


@router.put("/accounts/{account_id}/limits")
def set_limits(account_id: uuid.UUID, body: LimitsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return accounts.set_limits(db, user, account_id, **body.model_dump())


@router.post("/accounts/{account_id}/unlock")
def unlock(account_id: uuid.UUID, body: UnlockIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return accounts.unlock_account(db, user, account_id, body.code)


@router.get("/accounts/{account_id}/close-check")
def close_check(account_id: uuid.UUID, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.close_check(db, user_id, account_id)


@router.post("/accounts/{account_id}/close")
def close_account(account_id: uuid.UUID, body: PinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return accounts.close_account(db, user, account_id, body.pin)


@router.post("/accounts/{account_id}/statements", status_code=202)
def statement(account_id: uuid.UUID, body: StatementIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return accounts.request_statement(db, user_id, account_id, **body.model_dump())


@router.post("/pin/verify", status_code=204)
def verify(body: VerifyPinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    account = accounts.get_owned_account(db, user.id, body.account_id) if body.account_id else None
    verify_pin(db, user, body.pin, account)
