import calendar
import hashlib
import json
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import KST, Account, AutoTransfer, Transfer, User, now_kst
from app.security import verify_pin
from app.services import notifications
from app.services.accounts import assert_allowed, get_owned_account
from app.services.transfers import find_recipient, recipient_name, transfer
from app.services.verification import aware


def next_run(cycle: str, run_day: int | None, start_date: date, end_date: date | None, after: datetime) -> datetime | None:
    """기획서 미정 기본값: KST 09시, 없는 날짜는 말일, 지난 회차는 한 번만 실행."""
    after = aware(after).astimezone(KST)
    day = max(start_date, after.date())
    if cycle == "WEEKLY":
        day += timedelta(days=(run_day - day.weekday()) % 7)
        candidate = datetime.combine(day, time(9), KST)
        if candidate <= after:
            candidate += timedelta(days=7)
    elif cycle == "MONTHLY":
        year, month = day.year, day.month
        while True:
            chosen = date(year, month, min(run_day, calendar.monthrange(year, month)[1]))
            candidate = datetime.combine(chosen, time(9), KST)
            if chosen >= start_date and candidate > after:
                break
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    else:
        return None
    return candidate if end_date is None or candidate.date() <= end_date else None


def auto_out(db: Session, row: AutoTransfer, user_id) -> dict:
    target = db.get(Account, row.to_account_id)
    last = db.scalar(select(Transfer).where(Transfer.auto_transfer_id == row.id).order_by(Transfer.request_at.desc(), Transfer.id.desc()).limit(1))
    return {k: getattr(row, k) for k in ("id", "from_account_id", "amount", "memo", "cycle", "run_day", "start_date", "end_date", "next_run_at", "status", "created_at")} | {
        "to_account_num": target.account_num, "holder_name": recipient_name(db, target, user_id),
        "last_run": {"transfer_id": last.id, "status": last.status, "fail_reason": last.fail_reason, "complete_at": last.complete_at} if last else None,
    }


def registered_result(db: Session, user_id, row: AutoTransfer, source: Account, fingerprint: str) -> dict:
    if row.from_account_id != source.id or row.registration_fingerprint != fingerprint:
        raise BankError("SCHEDULE_CONFLICT", "이미 사용한 예약 요청 번호예요. 예약 내역을 확인해 주세요.", 409)
    return auto_out(db, row, user_id)


def register(db: Session, user: User, *, idempotency_key: uuid.UUID, from_account_id, to_account_num: str, amount: int, pin: str,
             cycle: str, run_at: datetime | None, run_day: int | None, start_date: date | None,
             end_date: date | None, memo: str | None) -> dict:
    source = get_owned_account(db, user.id, from_account_id)
    verify_pin(db, user, pin, source)
    return register_after_pin(db, user.id, idempotency_key=idempotency_key, from_account_id=from_account_id,
                              to_account_num=to_account_num, amount=amount, cycle=cycle, run_at=run_at,
                              run_day=run_day, start_date=start_date, end_date=end_date, memo=memo)


def register_after_pin(db: Session, user_id: uuid.UUID, *, idempotency_key: uuid.UUID, from_account_id, to_account_num: str,
                       amount: int, cycle: str, run_at: datetime | None, run_day: int | None,
                       start_date: date | None, end_date: date | None, memo: str | None,
                       expected_next: datetime | None = None) -> dict:
    source = get_owned_account(db, user_id, from_account_id, lock=True)
    if run_at is not None and run_at.tzinfo is not None:
        run_at = run_at.astimezone(KST)
    fingerprint = hashlib.sha256(json.dumps(
        (to_account_num, amount, cycle, run_at, run_day, start_date, end_date, memo), default=str
    ).encode()).hexdigest()
    existing = db.get(AutoTransfer, idempotency_key)
    if existing is not None:
        return registered_result(db, user_id, existing, source, fingerprint)
    assert_allowed(source, "WITHDRAW")
    if type(amount) is not int or amount <= 0:
        raise BankError("INVALID_AMOUNT", "이체 금액을 확인해 주세요.")
    target = find_recipient(db, to_account_num, user_id)
    if target.id == source.id:
        raise BankError("SAME_ACCOUNT", "출금 계좌와 같은 계좌로는 보낼 수 없어요.")
    now = now_kst()
    if cycle == "ONCE":
        if run_at is None or run_at.tzinfo is None or run_day is not None:
            raise BankError("INVALID_TIME", "예약 시각에는 시간대와 미래 시각을 지정해 주세요.")
        next_at = run_at.astimezone(KST)
        start_date = start_date or next_at.date()
        if next_at <= now or next_at.date() < start_date or (end_date and next_at.date() > end_date):
            raise BankError("INVALID_TIME", "예약 시각과 이체 기간을 확인해 주세요.")
    else:
        valid_day = type(run_day) is int and ((cycle == "WEEKLY" and 0 <= run_day <= 6) or (cycle == "MONTHLY" and 1 <= run_day <= 31))
        if not valid_day or run_at is not None:
            raise BankError("INVALID_TIME", "주기와 실행일을 확인해 주세요.")
        start_date = start_date or now.date()
        next_at = next_run(cycle, run_day, start_date, end_date, now)
        if next_at is None:
            raise BankError("INVALID_TIME", "이체 기간 안에 실행 가능한 날짜가 없어요.")
    if end_date and end_date < start_date:
        raise BankError("INVALID_TIME", "종료일은 시작일보다 빠를 수 없어요.")
    if expected_next is not None and next_at != expected_next:
        raise BankError("INVALID_TIME", "첫 이체 예정일이 바뀌었어요. 자동이체 조건을 다시 확인해 주세요.", 409)
    row = AutoTransfer(id=idempotency_key, registration_fingerprint=fingerprint,
        from_account_id=source.id, to_account_id=target.id, amount=amount, memo=memo,
        cycle=cycle, run_day=run_day, start_date=start_date, end_date=end_date, next_run_at=next_at)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.get(AutoTransfer, idempotency_key)
        if existing is None:
            raise
        return registered_result(db, user_id, existing, source, fingerprint)
    return auto_out(db, row, user_id)


def list_schedules(db: Session, user_id, status: str | None) -> list[dict]:
    query = select(AutoTransfer).join(Account, AutoTransfer.from_account_id == Account.id).where(Account.user_id == user_id)
    if status:
        query = query.where(AutoTransfer.status == status)
    return [auto_out(db, row, user_id) for row in db.scalars(query.order_by(AutoTransfer.next_run_at, AutoTransfer.id))]


def cancel(db: Session, user_id, schedule_id) -> None:
    owned = select(Account.id).where(Account.user_id == user_id)
    row = db.scalar(select(AutoTransfer).where(AutoTransfer.id == schedule_id, AutoTransfer.from_account_id.in_(owned))
        .with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise BankError("INVALID_ACCOUNT", "자동이체를 찾을 수 없어요.", 404)
    if row.status == "ENDED":
        raise BankError("INVALID_TIME", "이미 종료된 이체예요.")
    row.status = "CANCELED"
    db.commit()


def process_one(db: Session, schedule_id, at: datetime) -> bool:
    """회차 이체·결과·다음 회차·실패 알림을 같은 트랜잭션으로 확정한다."""
    at = aware(at).astimezone(KST)
    row = db.scalar(select(AutoTransfer).where(AutoTransfer.id == schedule_id, AutoTransfer.status == "ACTIVE",
        AutoTransfer.next_run_at <= at).with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if row is None:
        return False
    planned = aware(row.next_run_at).astimezone(KST)
    if row.end_date and (planned.date() > row.end_date or at.date() > row.end_date):
        row.status = "ENDED"
        db.commit()
        return False
    key = f"auto:{row.id}:{planned:%Y%m%d%H%M}"
    try:
        # 이체 실패만 저장점까지 되돌리고 회차·실패 기록은 남긴다.
        with db.begin_nested():
            transfer(db, row.from_account_id, row.to_account_id, row.amount, key, row.memo, row.id, commit=False)
    except BankError as error:
        db.add(Transfer(idempotency_key=key, from_account_id=row.from_account_id, to_account_id=row.to_account_id,
            amount=row.amount, memo=row.memo, status="FAILED", auto_transfer_id=row.id,
            fail_reason=error.message[:200], request_at=at, complete_at=at))
        owner_id = db.get(Account, row.from_account_id).user_id
        notifications.create(db, owner_id, "AUTO_TRANSFER_FAIL", "자동·예약이체에 실패했어요. " + error.message)
    following = next_run(row.cycle, row.run_day, row.start_date, row.end_date, max(at, planned))
    if following is None:
        row.status = "ENDED"
    else:
        row.next_run_at = following
    db.commit()
    return True
