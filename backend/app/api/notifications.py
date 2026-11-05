import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.security import current_user_id
from app.services import notifications

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    return notifications.list_notifications(db, user_id)


@router.post("/read-all", status_code=204)
def read_all(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    notifications.mark_all_read(db, user_id)
    return Response(status_code=204)
