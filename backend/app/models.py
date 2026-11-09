"""모든 테이블. docs/bank.dbml과 테이블·컬럼 이름이 1:1로 같다. 바꿀 때는 DBML도 같이 바꾼다.

금액은 전부 원 단위 BigInteger. 상태값은 문자열(DBML note의 값만 사용).
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import DateTime

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없어서 고정 오프셋으로 충분

# SQLite(테스트)는 INTEGER PRIMARY KEY 만 자동 증가
BigId = BigInteger().with_variant(Integer, "sqlite")
Json = JSON().with_variant(JSONB, "postgresql")
Ts = DateTime(timezone=True)


def now_kst() -> datetime:
    return datetime.now(KST)


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def big_pk() -> Mapped[int]:
    return mapped_column(BigId, primary_key=True, autoincrement=True)


def ref(target: str, nullable: bool = False, kind=Uuid):
    return mapped_column(kind, ForeignKey(target), nullable=nullable)


def created() -> Mapped[datetime]:
    return mapped_column(Ts, default=now_kst)


# ===== A. 회원·인증 =====

class User(Base):
    """회원. 로그인 ID는 email."""
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True)
    user_name: Mapped[str] = mapped_column(String(50))
    birth: Mapped[date | None]
    phone_num: Mapped[str | None] = mapped_column(String(20), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    pin: Mapped[str] = mapped_column(String(255))  # PIN 6자리 해시
    login_fail_count: Mapped[int] = mapped_column(default=0)
    pin_fail_count: Mapped[int] = mapped_column(default=0)
    auth_version: Mapped[int] = mapped_column(default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / LOCKED / WITHDRAWN
    created_at: Mapped[datetime] = created()
    withdrawn_at: Mapped[datetime | None] = mapped_column(Ts)


class Term(Base):
    """약관"""
    __tablename__ = "terms"
    id: Mapped[int] = big_pk()
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(20))
    required: Mapped[bool]
    category: Mapped[str] = mapped_column(String(20))  # SIGNUP / ACCOUNT_OPEN


class TermAgreement(Base):
    """약관 동의 내역"""
    __tablename__ = "term_agreements"
    id: Mapped[int] = big_pk()
    user_id: Mapped[uuid.UUID] = ref("users.id")
    term_id: Mapped[int] = ref("terms.id", kind=BigInteger)
    agreed: Mapped[bool]
    agreed_at: Mapped[datetime] = created()


class VerificationCode(Base):
    """본인확인 인증번호 (이메일 발송)"""
    __tablename__ = "verification_codes"
    id: Mapped[int] = big_pk()
    email: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(20))  # SIGNUP / UNLOCK_ACCOUNT / RESET_PW
    code_hash: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(Ts)
    attempts: Mapped[int] = mapped_column(default=0)
    verified_at: Mapped[datetime | None] = mapped_column(Ts)


class LoginHistory(Base):
    """로그인 접속 기록"""
    __tablename__ = "login_histories"
    id: Mapped[int] = big_pk()
    user_id: Mapped[uuid.UUID] = ref("users.id")
    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    success: Mapped[bool]
    created_at: Mapped[datetime] = created()


class Notification(Base):
    """알림"""
    __tablename__ = "notifications"
    id: Mapped[int] = big_pk()
    user_id: Mapped[uuid.UUID] = ref("users.id")
    type: Mapped[str] = mapped_column(String(30))  # CARD_PAYMENT / SUSPICIOUS_LOGIN / AUTO_TRANSFER_FAIL
    message: Mapped[str] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(Ts)
    created_at: Mapped[datetime] = created()


# ===== B. 계좌 =====

class AccountProduct(Base):
    """계좌 상품. code는 프론트 src/data/mock.ts의 상품 id와 같다."""
    __tablename__ = "account_products"
    id: Mapped[int] = big_pk()
    code: Mapped[str] = mapped_column(String(20), unique=True)
    product_name: Mapped[str] = mapped_column(String(100))
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 3))
    description: Mapped[str | None] = mapped_column(Text)


class Account(Base):
    """계좌"""
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("balance >= 0", name="ck_accounts_balance_nonneg"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = ref("users.id")
    product_id: Mapped[int] = ref("account_products.id", kind=BigInteger)
    account_num: Mapped[str] = mapped_column(String(13), unique=True)  # xxx-xxxx-xxxx
    account_password: Mapped[str] = mapped_column(String(255))  # 4자리 해시
    password_fail_count: Mapped[int] = mapped_column(default=0)
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    nickname: Mapped[str | None] = mapped_column(String(50))
    is_favorite: Mapped[bool] = mapped_column(default=False)
    daily_limit: Mapped[int] = mapped_column(BigInteger, default=1_000_000)
    month_limit: Mapped[int] = mapped_column(BigInteger, default=5_000_000)
    opening_info: Mapped[dict | None] = mapped_column(Json)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / SUSPENDED / CLOSED
    created_at: Mapped[datetime] = created()
    closed_at: Mapped[datetime | None] = mapped_column(Ts)


class AccountTransaction(Base):
    """계좌 거래내역 (거래원장). 돈이 움직일 때만 쓰고 수정·삭제하지 않는다."""
    __tablename__ = "account_transactions"
    __table_args__ = (Index("idx_account_transactions_account_at", "account_id", "transaction_at"),)
    id: Mapped[int] = big_pk()
    account_id: Mapped[uuid.UUID] = ref("accounts.id")
    transfer_id: Mapped[uuid.UUID | None] = ref("transfers.id", nullable=True)
    card_payment_id: Mapped[int | None] = ref("card_payments.id", nullable=True, kind=BigInteger)
    transaction_type: Mapped[str] = mapped_column(String(20))  # DEPOSIT / WITHDRAW / TRANSFER / AUTO_TRANSFER / CARD
    transaction_direction: Mapped[str] = mapped_column(String(3))  # IN / OUT
    amount: Mapped[int] = mapped_column(BigInteger)
    new_balance: Mapped[int] = mapped_column(BigInteger)
    counterparty_name: Mapped[str | None] = mapped_column(String(100))
    counterparty_account: Mapped[str | None] = mapped_column(String(13))
    memo: Mapped[str | None] = mapped_column(String(100))
    transaction_at: Mapped[datetime] = created()


class StatementRequest(Base):
    """거래내역 다운로드 신청"""
    __tablename__ = "statement_requests"
    id: Mapped[int] = big_pk()
    account_id: Mapped[uuid.UUID] = ref("accounts.id")
    from_date: Mapped[date]
    to_date: Mapped[date]
    email: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="REQUESTED")  # REQUESTED / SENT / FAILED
    created_at: Mapped[datetime] = created()


# ===== C. 이체 =====

class Transfer(Base):
    """이체"""
    __tablename__ = "transfers"
    id: Mapped[uuid.UUID] = uuid_pk()
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    from_account_id: Mapped[uuid.UUID] = ref("accounts.id")
    to_account_id: Mapped[uuid.UUID] = ref("accounts.id")
    auto_transfer_id: Mapped[uuid.UUID | None] = ref("auto_transfers.id", nullable=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    memo: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))  # PENDING / SUCCESS / FAILED
    fail_reason: Mapped[str | None] = mapped_column(String(200))
    request_at: Mapped[datetime] = created()
    complete_at: Mapped[datetime | None] = mapped_column(Ts)


class AutoTransfer(Base):
    """자동이체·예약이체"""
    __tablename__ = "auto_transfers"
    __table_args__ = (Index("idx_auto_transfers_next_run", "next_run_at"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    registration_fingerprint: Mapped[str | None] = mapped_column(String(64))
    from_account_id: Mapped[uuid.UUID] = ref("accounts.id")
    to_account_id: Mapped[uuid.UUID] = ref("accounts.id")
    amount: Mapped[int] = mapped_column(BigInteger)
    memo: Mapped[str | None] = mapped_column(String(100))
    cycle: Mapped[str] = mapped_column(String(10))  # ONCE / WEEKLY / MONTHLY
    run_day: Mapped[int | None]  # WEEKLY 0(월)~6 / MONTHLY 1~31 / ONCE는 None
    start_date: Mapped[date]
    end_date: Mapped[date | None]
    next_run_at: Mapped[datetime] = mapped_column(Ts)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / ENDED / CANCELED
    created_at: Mapped[datetime] = created()


class FavoriteRecipient(Base):
    """자주 쓰는 받는 계좌"""
    __tablename__ = "favorite_recipients"
    id: Mapped[int] = big_pk()
    user_id: Mapped[uuid.UUID] = ref("users.id")
    account_num: Mapped[str] = mapped_column(String(13))
    holder_name: Mapped[str] = mapped_column(String(50))
    alias: Mapped[str | None] = mapped_column(String(50))


# ===== D. 카드 =====

class Card(Base):
    """체크카드"""
    __tablename__ = "cards"
    id: Mapped[uuid.UUID] = uuid_pk()
    account_id: Mapped[uuid.UUID] = ref("accounts.id")
    card_number: Mapped[str] = mapped_column(String(255), unique=True)  # 암호화 저장
    expiry_date: Mapped[str] = mapped_column(String(5))  # MM/YY
    card_network: Mapped[str | None] = mapped_column(String(20))
    daily_limit: Mapped[int] = mapped_column(BigInteger, default=1_000_000)
    overseas_enabled: Mapped[bool] = mapped_column(default=False)
    reissued_from_id: Mapped[uuid.UUID | None] = ref("cards.id", nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE / SUSPENDED / LOST / REISSUED / CANCELED
    created_at: Mapped[datetime] = created()


class CardPayment(Base):
    """카드 결제내역"""
    __tablename__ = "card_payments"
    __table_args__ = (Index("idx_card_payments_card_id", "card_id"), UniqueConstraint("card_id", "idempotency_key", name="uq_card_payment_request"))
    id: Mapped[int] = big_pk()
    card_id: Mapped[uuid.UUID] = ref("cards.id")
    idempotency_key: Mapped[str | None] = mapped_column(String(64))  # 기존 결제는 NULL
    overseas: Mapped[bool | None]
    amount: Mapped[int] = mapped_column(BigInteger)
    place: Mapped[str | None] = mapped_column(String(100))
    category: Mapped[str | None] = mapped_column(String(30))
    request_at: Mapped[datetime] = created()
    complete_at: Mapped[datetime | None] = mapped_column(Ts)
