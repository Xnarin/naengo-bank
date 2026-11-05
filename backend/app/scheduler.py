import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.db import SessionLocal
from app.models import KST, AutoTransfer, now_kst
from app.services.auto_transfers import process_one

logger = logging.getLogger(__name__)


def run_due(session_factory=SessionLocal, at=None):
    at = at or now_kst()
    with session_factory() as db:
        ids = list(db.scalars(select(AutoTransfer.id).where(AutoTransfer.status == "ACTIVE", AutoTransfer.next_run_at <= at)))
    for schedule_id in ids:
        try:
            with session_factory() as db:
                process_one(db, schedule_id, at)
        except Exception:
            logger.exception("자동이체 실행 중 오류: %s", schedule_id)


def create_scheduler():
    # shortcut: 단일 API 프로세스 운영. 여러 워커로 늘리면 스케줄러를 별도 프로세스로 분리한다.
    scheduler = BackgroundScheduler(timezone=KST)
    scheduler.add_job(run_due, "interval", minutes=1, max_instances=1, coalesce=True, next_run_time=now_kst())
    return scheduler
