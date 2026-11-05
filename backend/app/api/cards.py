import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user, current_user_id
from app.services import cards

router = APIRouter(prefix="/cards", tags=["cards"])


class IssueIn(BaseModel):
    account_id: uuid.UUID
    daily_limit: int = Field(default=1_000_000, gt=0, le=10_000_000, strict=True)
    overseas_enabled: bool = False


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^[0-9]{6}$")


class UpdateIn(PinIn):
    daily_limit: int | None = Field(default=None, gt=0, le=10_000_000, strict=True)
    overseas_enabled: bool | None = None


class PaymentIn(BaseModel):
    amount: int = Field(gt=0, strict=True)
    place: str = Field(min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=30)
    overseas: bool = False


@router.post("", status_code=201)
def issue(body: IssueIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return cards.issue(db, user_id, **body.model_dump())


@router.get("")
def list_cards(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return cards.list_cards(db, user_id)


@router.get("/{card_id}")
def detail(card_id: uuid.UUID, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return cards.card_out(cards.get_owned_card(db, user_id, card_id))


@router.patch("/{card_id}")
def update(card_id: uuid.UUID, body: UpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cards.authorize(db, user, card_id, body.pin)
    return cards.update_card(db, user.id, card_id, body.daily_limit, body.overseas_enabled)


def status_route(path: str, status: str):
    def action(card_id: uuid.UUID, body: PinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
        cards.authorize(db, user, card_id, body.pin)
        return cards.card_out(cards.set_card_status(db, user.id, card_id, status))
    router.add_api_route("/{card_id}/" + path, action, methods=["POST"], name=path)


for path, status in (("lost", "LOST"), ("suspend", "SUSPENDED"), ("resume", "ACTIVE"), ("cancel", "CANCELED")):
    status_route(path, status)


@router.post("/{card_id}/reissue", status_code=201)
def reissue(card_id: uuid.UUID, body: PinIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cards.authorize(db, user, card_id, body.pin)
    return cards.reissue(db, user.id, card_id)


@router.get("/{card_id}/payments")
def payments(card_id: uuid.UUID, month: str | None = Query(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$"),
             user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return cards.payments(db, user_id, card_id, month)


@router.post("/{card_id}/payments", status_code=201)
def pay(card_id: uuid.UUID, body: PaymentIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return cards.pay(db, user_id, card_id, **body.model_dump())
