import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user, current_user_id
from app.services import auto_transfers

router = APIRouter(prefix="/auto-transfers", tags=["auto-transfers"])


class AutoIn(BaseModel):
    idempotency_key: uuid.UUID
    from_account_id: uuid.UUID
    to_account_num: str = Field(pattern=r"^[0-9]{3}-[0-9]{4}-[0-9]{4}$")
    amount: int = Field(gt=0, strict=True)
    pin: str = Field(pattern=r"^[0-9]{6}$")
    memo: str | None = Field(default=None, max_length=100)
    cycle: Literal["ONCE", "WEEKLY", "MONTHLY"]
    run_at: datetime | None = None
    run_day: int | None = Field(default=None, strict=True)
    start_date: date | None = None
    end_date: date | None = None


@router.post("", status_code=201)
def register(body: AutoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return auto_transfers.register(db, user, **body.model_dump())


@router.get("")
def list_schedules(status: Literal["ACTIVE", "ENDED", "CANCELED"] | None = None,
                   user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return auto_transfers.list_schedules(db, user_id, status)


@router.delete("/{schedule_id}", status_code=204)
def cancel(schedule_id: uuid.UUID, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    auto_transfers.cancel(db, user_id, schedule_id)
    return Response(status_code=204)
