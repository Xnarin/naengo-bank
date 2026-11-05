import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import current_user_id
from app.services import notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


class ReadIn(BaseModel):
    ids: list[int] | None = None


@router.get("")
def list_notifications(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return notifications.list_notifications(db, user_id)


@router.post("/read-all", status_code=204)
def read_all(body: ReadIn | None = None, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    notifications.mark_all_read(db, user_id, body.ids if body else None)
    return Response(status_code=204)
