from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Notification, now_kst


def create(db: Session, user_id, kind: str, message: str) -> None:
    db.add(Notification(user_id=user_id, type=kind, message=message))


def list_notifications(db: Session, user_id) -> dict:
    query = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc(), Notification.id.desc())
    items = [{k: getattr(n, k) for k in ("id", "type", "message", "read_at", "created_at")} for n in db.scalars(query)]
    unread = db.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None)))
    return {"items": items, "unread": unread}


def mark_all_read(db: Session, user_id) -> None:
    db.execute(update(Notification).where(Notification.user_id == user_id, Notification.read_at.is_(None)).values(read_at=now_kst()))
    db.commit()
