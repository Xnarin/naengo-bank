import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import BankError
from app.models import Account, User, now_kst

MAX_FAILS = 5  # 기획서 미정, 기본값
_ph = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)  # 토큰 없음도 AUTH 에러 형식으로 응답


def hash_secret(raw: str) -> str:
    return _ph.hash(raw)


def verify_secret(hashed: str, raw: str) -> bool:
    try:
        return _ph.verify(hashed, raw)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: uuid.UUID, auth_version: int = 0) -> str:
    exp = now_kst() + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp, "ver": auth_version}, settings.jwt_secret, algorithm="HS256")


def current_user_id(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> uuid.UUID:
    """모든 보호 API의 진입점. user_id 는 오직 이 토큰에서만 나온다."""
    try:
        claims = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=["HS256"], options={"require": ["sub", "exp"]})
        user_id = uuid.UUID(claims["sub"])
    except (AttributeError, KeyError, TypeError, ValueError, jwt.PyJWTError):
        raise BankError("AUTH", "로그인이 만료됐어요. 다시 로그인해 주세요.", 401)
    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요. 다시 로그인해 주세요.", 401)
    if claims.get("ver", 0) != user.auth_version:
        raise BankError("AUTH", "로그인이 만료됐어요. 다시 로그인해 주세요.", 401)
    return user_id


def current_user(user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요. 다시 로그인해 주세요.", 401)
    return user


def verify_pin(db: Session, user: User, pin: str, account: Account | None = None) -> None:
    """PIN 확인 (결정 D4). 실패 횟수는 즉시 commit (뒤 작업이 rollback 돼도 남도록).

    5회째 틀리면: 계좌 작업 중(account 있음)이면 그 계좌를 거래중지, 아니면(PIN 로그인) 회원 잠금.
    """
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요. 다시 로그인해 주세요.", 401)
    if account is not None:
        account = db.scalar(select(Account).where(Account.id == account.id).with_for_update().execution_options(populate_existing=True))
    if account is not None and account.status == "SUSPENDED":
        raise BankError("PIN_LOCKED", "거래가 중지된 계좌예요. 계좌 관리에서 본인인증으로 해제해 주세요.", 403)
    if account is not None and account.status == "CLOSED":
        raise BankError("INVALID_FROM", "해지된 계좌에서는 할 수 없어요.")
    if verify_secret(user.pin, pin):
        user.pin_fail_count = 0
        db.commit()
        return
    user.pin_fail_count += 1
    if user.pin_fail_count >= MAX_FAILS:
        user.pin_fail_count = 0
        if account is not None:
            account.status = "SUSPENDED"
            db.commit()
            raise BankError("PIN_LOCKED", "비밀번호를 5회 틀려 이 계좌의 거래가 중지됐어요. 계좌 관리에서 본인인증으로 해제할 수 있어요.", 403)
        user.status = "LOCKED"
        db.commit()
        raise BankError("USER_LOCKED", "비밀번호를 5회 틀려 계정이 잠겼어요. 비밀번호 재설정으로 풀어 주세요.", 403)
    db.commit()
    raise BankError("PIN", f"비밀번호가 맞지 않아요. ({user.pin_fail_count}/{MAX_FAILS})", 401)
