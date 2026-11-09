import secrets
import uuid
import calendar
import csv
import io
from datetime import date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import KST, Account, AccountProduct, AccountTransaction, AutoTransfer, Card, StatementRequest, Term, TermAgreement, Transfer, User, now_kst
from app.security import hash_secret, verify_pin
from app.services import mail, verification

# B5.2 계좌 상태별 허용 동작 (거래중지 해제 UNLOCK은 SUSPENDED 전용 예외)
ALLOWED = {
    "ACTIVE": {"READ", "DEPOSIT", "WITHDRAW", "MANAGE", "CLOSE"},
    "SUSPENDED": {"READ", "UNLOCK"},
    "CLOSED": {"READ"},
}


def assert_allowed(account: Account, action: str) -> None:
    if action in ALLOWED[account.status]:
        return
    if account.status == "SUSPENDED":
        raise BankError("SUSPENDED", "거래가 중지된 계좌예요. 계좌 관리에서 본인인증으로 해제해 주세요.")
    raise BankError("INVALID_FROM", "해지된 계좌에서는 할 수 없어요.")


def get_owned_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID, *, lock: bool = False) -> Account:
    """B5.1 소유자 확인. 남의 계좌는 '없음'과 똑같이 응답해 존재 여부도 숨긴다."""
    query = select(Account).where(Account.id == account_id, Account.user_id == user_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    acc = db.scalar(query)
    if acc is None:
        raise BankError("INVALID_FROM", "계좌를 찾을 수 없어요.", 404)
    return acc


def new_account_num(db: Session) -> str:
    """3-4-4 계좌번호. 최종 중복 방지는 accounts.account_num UNIQUE 제약."""
    while True:
        n = f"{secrets.randbelow(900) + 100}-{secrets.randbelow(10**4):04}-{secrets.randbelow(10**4):04}"
        if not db.scalar(select(Account.id).where(Account.account_num == n)):
            return n


def mask_name(name: str) -> str:
    return name[0] + "*" * (len(name) - 2) + name[-1] if len(name) > 2 else name[0] + "*"


def account_out(db: Session, account: Account, *, masked: bool = False) -> dict:
    product = db.get(AccountProduct, account.product_id)
    result = {k: getattr(account, k) for k in (
        "id", "account_num", "nickname", "balance", "status", "is_favorite",
        "daily_limit", "month_limit", "created_at", "closed_at",
    )}
    if masked:
        result["account_num"] = account.account_num[:4] + "****" + account.account_num[8:]
    return result | {"product_code": product.code, "product_name": product.product_name}


def list_products(db: Session) -> list[dict]:
    return [{"code": p.code, "product_name": p.product_name, "interest_rate": p.interest_rate}
            for p in db.scalars(select(AccountProduct).order_by(AccountProduct.id))]


def list_accounts(db: Session, user_id: uuid.UUID, status: str) -> list[dict]:
    closed = Account.status == "CLOSED"
    query = select(Account).where(Account.user_id == user_id, closed if status == "closed" else ~closed)
    query = query.order_by(Account.is_favorite.desc(), Account.created_at, Account.id)
    return [account_out(db, a, masked=True) for a in db.scalars(query)]


def account_usage(db: Session, account: Account) -> dict:
    day_start = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
    def spent(since):
        return db.scalar(select(func.coalesce(func.sum(AccountTransaction.amount), 0))
            .join(Transfer, AccountTransaction.transfer_id == Transfer.id)
            .join(Account, Transfer.to_account_id == Account.id)
            .where(AccountTransaction.account_id == account.id,
                   AccountTransaction.transaction_direction == "OUT",
                   AccountTransaction.transaction_type.in_(("TRANSFER", "AUTO_TRANSFER")),
                   AccountTransaction.transaction_at >= since,
                   Account.user_id != account.user_id))
    return {"today_used": spent(day_start), "month_used": spent(day_start.replace(day=1))}


def get_account(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> dict:
    account = get_owned_account(db, user_id, account_id)
    return account_out(db, account) | account_usage(db, account)


def open_account(db: Session, user_id: uuid.UUID, *, product_code: str, password: str,
                 password_confirm: str, opening_info: dict, nickname: str | None,
                 agreed_term_ids: list[int]) -> dict:
    # 탈퇴와 개설을 직렬화한다. 탈퇴 처리도 사용자 행을 먼저 잠근다.
    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요.", 401)
    product = db.scalar(select(AccountProduct).where(AccountProduct.code == product_code))
    if product is None:
        raise BankError("INVALID_PRODUCT", "상품 정보를 찾을 수 없어요.", 404)
    if password != password_confirm:
        raise BankError("PASSWORD_MISMATCH", "통장 비밀번호가 서로 달라요.")
    if not opening_info:
        raise BankError("INVALID_ACCOUNT", "계좌 개설 목적과 거래정보를 입력해 주세요.")
    terms = list(db.scalars(select(Term).where(Term.category == "ACCOUNT_OPEN")))
    agreed = set(agreed_term_ids)
    if not terms or not {t.id for t in terms if t.required} <= agreed or not agreed <= {t.id for t in terms}:
        raise BankError("TERMS_REQUIRED", "필수 약관에 동의해 주세요.")
    password_hash = hash_secret(password)
    for _ in range(5):
        account = Account(user_id=user_id, product_id=product.id, account_num=new_account_num(db),
                          account_password=password_hash, opening_info=opening_info, nickname=nickname)
        try:
            # UNIQUE 충돌만 저장점까지 되돌려 사용자 잠금과 약관 트랜잭션을 유지한다.
            with db.begin_nested():
                db.add(account)
                db.flush()
            break
        except IntegrityError:
            if not db.scalar(select(Account.id).where(Account.account_num == account.account_num)):
                raise
    else:
        raise BankError("INVALID_ACCOUNT", "계좌번호를 발급하지 못했어요. 다시 시도해 주세요.")
    db.add_all([TermAgreement(user_id=user_id, term_id=t.id, agreed=t.id in agreed) for t in terms])
    db.commit()
    return account_out(db, account)


def transaction_out(tx: AccountTransaction) -> dict:
    return {k: getattr(tx, k) for k in ("id", "account_id", "transaction_type", "transaction_direction",
        "amount", "new_balance", "counterparty_name", "counterparty_account", "memo", "transaction_at")}


def date_range(start: date | None, end: date | None) -> tuple[date, date]:
    end = end or now_kst().date()
    if start is None:
        month_index = end.year * 12 + end.month - 1 - 3
        year, month = divmod(month_index, 12)
        if year < 1:
            raise BankError("INVALID_TIME", "조회 기간을 확인해 주세요.")
        start = date(year, month + 1, min(end.day, calendar.monthrange(year, month + 1)[1]))
    if start > end:
        raise BankError("INVALID_TIME", "시작일은 종료일보다 늦을 수 없어요.")
    return start, end


def list_transactions(db: Session, user_id: uuid.UUID, account_id: uuid.UUID, *,
                      start: date | None = None, end: date | None = None, direction: str = "ALL",
                      order: str = "desc", transaction_type: str | None = None,
                      min_amount: int | None = None, max_amount: int | None = None,
                      amount: int | None = None, q: str | None = None) -> list[dict]:
    account = get_owned_account(db, user_id, account_id)
    assert_allowed(account, "READ")
    start, end = date_range(start, end)
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise BankError("INVALID_AMOUNT", "최소 금액은 최대 금액보다 클 수 없어요.")
    T = AccountTransaction
    query = select(T).where(T.account_id == account_id,
        T.transaction_at >= datetime.combine(start, time.min, KST),
        T.transaction_at <= datetime.combine(end, time.max, KST))
    if direction != "ALL":
        query = query.where(T.transaction_direction == direction)
    if transaction_type:
        query = query.where(T.transaction_type == transaction_type)
    if min_amount is not None:
        query = query.where(T.amount >= min_amount)
    if max_amount is not None:
        query = query.where(T.amount <= max_amount)
    if amount is not None:
        query = query.where(T.amount == amount)
    if q:
        query = query.where(or_(T.counterparty_name.contains(q, autoescape=True), T.memo.contains(q, autoescape=True)))
    query = query.order_by(T.transaction_at.desc(), T.id.desc()) if order == "desc" else query.order_by(T.transaction_at, T.id)
    return [transaction_out(t) for t in db.scalars(query)]


def get_transaction(db: Session, user_id: uuid.UUID, account_id: uuid.UUID, tx_id: int) -> dict:
    get_owned_account(db, user_id, account_id)
    tx = db.scalar(select(AccountTransaction).where(AccountTransaction.id == tx_id, AccountTransaction.account_id == account_id))
    if tx is None:
        raise BankError("INVALID_ACCOUNT", "거래내역을 찾을 수 없어요.", 404)
    return transaction_out(tx)


def toggle_favorite(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> dict:
    account = get_owned_account(db, user_id, account_id, lock=True)
    assert_allowed(account, "MANAGE")
    account.is_favorite = not account.is_favorite
    db.commit()
    return {"is_favorite": account.is_favorite}


def set_limits(db: Session, user: User, account_id: uuid.UUID, daily_limit: int, month_limit: int, pin: str) -> dict:
    if not 0 < daily_limit <= 10_000_000 or not 0 < month_limit <= 50_000_000 or daily_limit > month_limit:
        raise BankError("INVALID_LIMIT", "한도는 1일 1천만원·1달 5천만원 이하이며, 1일 한도가 1달 한도보다 클 수 없어요.")
    account = get_owned_account(db, user.id, account_id)
    assert_allowed(account, "MANAGE")
    verify_pin(db, user, pin, account)
    account = get_owned_account(db, user.id, account_id, lock=True)
    assert_allowed(account, "MANAGE")
    account.daily_limit, account.month_limit = daily_limit, month_limit
    db.commit()
    return account_out(db, account) | account_usage(db, account)


def unlock_account(db: Session, user: User, account_id: uuid.UUID, code: str) -> dict:
    user = db.scalar(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))
    account = get_owned_account(db, user.id, account_id, lock=True)
    if account.status != "SUSPENDED":
        raise BankError("INVALID_ACCOUNT", "거래중지 상태인 계좌만 해제할 수 있어요.")
    assert_allowed(account, "UNLOCK")
    verified = verification.verify_code(db, user.email, "UNLOCK_ACCOUNT", code)
    account.status, user.pin_fail_count = "ACTIVE", 0
    verification.consume(verified)
    db.commit()
    return account_out(db, account)


def close_blockers(db: Session, account: Account) -> list[dict]:
    blockers = []
    if account.status != "ACTIVE":
        blockers.append({"kind": "status", "text": "정상 상태인 계좌만 해지할 수 있어요."})
    if account.balance:
        blockers.append({"kind": "balance", "text": f"잔액 {account.balance:,}원이 남아 있어요. 다른 계좌로 옮겨 주세요."})
    if db.scalar(select(Card.id).where(Card.account_id == account.id, Card.status.notin_(("CANCELED", "REISSUED"))).limit(1)):
        blockers.append({"kind": "card", "text": "연결된 체크카드를 먼저 해지해 주세요."})
    if db.scalar(select(AutoTransfer.id).where(AutoTransfer.from_account_id == account.id, AutoTransfer.status == "ACTIVE").limit(1)):
        blockers.append({"kind": "auto_transfer", "text": "대기 중인 자동·예약이체를 먼저 해지해 주세요."})
    return blockers


def close_check(db: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> dict:
    blockers = close_blockers(db, get_owned_account(db, user_id, account_id))
    return {"closable": not blockers, "blockers": blockers}


def close_account(db: Session, user: User, account_id: uuid.UUID, pin: str) -> dict:
    account = get_owned_account(db, user.id, account_id)
    verify_pin(db, user, pin, account)
    account = get_owned_account(db, user.id, account_id, lock=True)
    blockers = close_blockers(db, account)
    if blockers:
        raise BankError("CLOSE_BLOCKED", blockers[0]["text"])
    account.status, account.closed_at, account.is_favorite = "CLOSED", now_kst(), False
    db.commit()
    return account_out(db, account)


def csv_cell(value):
    # 메모/상대방이 Excel 수식으로 실행되지 않도록 텍스트로 내보낸다.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def request_statement(db: Session, user_id: uuid.UUID, account_id: uuid.UUID, from_date: date, to_date: date, email: str) -> dict:
    from app.services.auth import DEMO_DOMAIN
    if db.get(User, user_id).email.endswith(DEMO_DOMAIN):
        raise BankError("AUTH", "체험에서는 거래내역을 이메일로 보낼 수 없어요.", 403)
    rows = list_transactions(db, user_id, account_id, start=from_date, end=to_date, order="asc")
    request = StatementRequest(account_id=account_id, from_date=from_date, to_date=to_date, email=email)
    db.add(request)
    db.commit()
    try:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["거래일시", "거래유형", "입출금", "금액", "거래후잔액", "상대방", "상대계좌", "적요"])
        for row in rows:
            writer.writerow([csv_cell(row[k]) for k in ("transaction_at", "transaction_type", "transaction_direction",
                "amount", "new_balance", "counterparty_name", "counterparty_account", "memo")])
        sent = mail.send_mail(email, "내금고 거래내역", f"{from_date} ~ {to_date} 거래내역을 첨부합니다.",
                             attachment=("transactions.csv", output.getvalue().encode("utf-8-sig")))
        request.status = "SENT" if sent else "FAILED"
    except Exception:
        request.status = "FAILED"
    db.commit()
    return {"id": request.id, "status": request.status}
