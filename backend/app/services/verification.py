import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import BankError
from app.models import KST, VerificationCode, now_kst
from app.security import MAX_FAILS, hash_secret, verify_secret
from app.services.mail import send_mail


def aware(value):
    # SQLite는 timezone 정보를 버린다. 실제 DB는 timestamptz를 사용한다.
    return value.replace(tzinfo=KST) if value.tzinfo is None else value


def latest(db: Session, email: str, purpose: str) -> VerificationCode:
    row = db.scalar(select(VerificationCode).where(
        VerificationCode.email == email.lower(), VerificationCode.purpose == purpose,
    ).order_by(VerificationCode.id.desc()).limit(1).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise BankError("CODE", "인증번호를 먼저 요청해 주세요.")
    return row


def request_code(db: Session, email: str, purpose: str) -> dict:
    code = f"{secrets.randbelow(1_000_000):06}"
    row = VerificationCode(email=email.lower(), purpose=purpose, code_hash=hash_secret(code),
                           expires_at=now_kst() + timedelta(minutes=3))
    db.add(row)
    try:
        db.flush()
        send_mail(email, "내금고 본인확인 인증번호", f"인증번호는 {code}입니다. 3분 안에 입력해 주세요.")
        db.commit()
    except Exception:
        db.rollback()
        raise BankError("CODE", "인증번호를 보내지 못했어요. 잠시 후 다시 시도해 주세요.")
    result = {"expires_at": row.expires_at}
    if settings.development and not settings.smtp_host:
        result["dev_code"] = code
    return result


def verify_code(db: Session, email: str, purpose: str, code: str) -> VerificationCode:
    row = latest(db, email, purpose)
    if row.attempts >= MAX_FAILS or aware(row.expires_at) <= now_kst():
        raise BankError("CODE", "인증번호가 만료됐어요. 새 번호를 요청해 주세요.")
    if not verify_secret(row.code_hash, code):
        row.attempts += 1
        db.commit()  # 후속 작업이 실패해도 시도 횟수를 보존한다.
        raise BankError("CODE", "인증번호가 맞지 않아요. 다시 확인해 주세요.")
    if row.verified_at is None:
        row.verified_at = now_kst()
    return row


def assert_verified(db: Session, email: str, purpose: str) -> VerificationCode:
    row = latest(db, email, purpose)
    if row.verified_at is None or aware(row.verified_at) < now_kst() - timedelta(minutes=10):
        raise BankError("CODE", "본인확인을 먼저 해 주세요.")
    return row


def consume(row: VerificationCode) -> None:
    row.verified_at = None
    row.expires_at = now_kst()
