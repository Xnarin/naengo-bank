import secrets

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import BankError
from app.models import Account, AccountTransaction, Card, CardPayment, User, now_kst
from app.security import verify_pin
from app.services.accounts import assert_allowed, get_owned_account
from app.services import notifications


def cipher() -> Fernet:
    try:
        return Fernet(settings.card_key.encode())
    except (AttributeError, ValueError):
        raise BankError("CARD_UNAVAILABLE", "카드 암호화 설정을 확인해 주세요.", 503)


def last4(card: Card) -> str:
    try:
        return cipher().decrypt(card.card_number.encode()).decode()[-4:]
    except (InvalidToken, UnicodeError):
        raise BankError("CARD_UNAVAILABLE", "카드 정보를 읽을 수 없어요.", 503)


def card_out(card: Card) -> dict:
    return {k: getattr(card, k) for k in ("id", "account_id", "expiry_date", "card_network", "daily_limit",
        "overseas_enabled", "status", "created_at")} | {"last4": last4(card)}


def get_owned_card(db: Session, user_id, card_id, *, lock=False) -> Card:
    card = db.scalar(select(Card).join(Account, Card.account_id == Account.id).where(Card.id == card_id, Account.user_id == user_id))
    if card is None:
        raise BankError("CARD_NOT_FOUND", "카드를 찾을 수 없어요.", 404)
    if lock:
        # 결제·관리·재발급 모두 계좌 → 카드 순서로 잠근다.
        get_owned_account(db, user_id, card.account_id, lock=True)
        card = db.scalar(select(Card).where(Card.id == card_id).with_for_update().execution_options(populate_existing=True))
    return card


def list_cards(db: Session, user_id) -> list[dict]:
    return [card_out(c) for c in db.scalars(select(Card).join(Account, Card.account_id == Account.id)
        .where(Account.user_id == user_id).order_by(Card.created_at.desc(), Card.id))]


def new_number() -> str:
    digits = "9" + "".join(str(secrets.randbelow(10)) for _ in range(14))
    total = 0
    for i, char in enumerate(digits):
        value = int(char) * (2 if i % 2 == 0 else 1)
        total += value - 9 if value > 9 else value
    return digits + str((-total) % 10)


def new_card(account_id, daily_limit, overseas_enabled, reissued_from_id=None) -> Card:
    now = now_kst()
    return Card(account_id=account_id, card_number=cipher().encrypt(new_number().encode()).decode(),
        expiry_date=f"{now.month:02}/{(now.year + 5) % 100:02}", card_network="LOCAL",
        daily_limit=daily_limit, overseas_enabled=overseas_enabled, reissued_from_id=reissued_from_id)


def validate_limit(value):
    if type(value) is not int or not 0 < value <= 10_000_000:
        raise BankError("CARD_LIMIT", "카드 한도는 0원 초과, 1천만원 이하로 입력해 주세요.")


def issue(db: Session, user_id, account_id, daily_limit: int, overseas_enabled: bool) -> dict:
    validate_limit(daily_limit)
    account = get_owned_account(db, user_id, account_id, lock=True)
    assert_allowed(account, "MANAGE")
    if db.scalar(select(Card.id).where(Card.account_id == account_id, Card.status.in_(("ACTIVE", "SUSPENDED", "LOST"))).limit(1)):
        raise BankError("CARD_UNAVAILABLE", "이 계좌에 연결된 카드가 있어요. 기존 카드를 해지하거나 재발급해 주세요.", 409)
    card = new_card(account.id, daily_limit, overseas_enabled)
    db.add(card)
    db.commit()
    return card_out(card)


def authorize(db: Session, user: User, card_id, pin: str) -> None:
    card = get_owned_card(db, user.id, card_id)
    verify_pin(db, user, pin, get_owned_account(db, user.id, card.account_id))


def set_card_status(db: Session, user_id, card_id, status: str) -> Card:
    """API·에이전트 공용. 호출자가 PIN 확인을 마친 뒤 호출한다."""
    card = get_owned_card(db, user_id, card_id, lock=True)
    assert_allowed(db.get(Account, card.account_id), "MANAGE")
    allowed = {"ACTIVE": {"SUSPENDED", "LOST", "CANCELED"}, "SUSPENDED": {"ACTIVE", "LOST", "CANCELED"}, "LOST": {"CANCELED"}}
    if card.status != status:
        if status not in allowed.get(card.status, set()):
            raise BankError("CARD_UNAVAILABLE", "현재 카드 상태에서는 변경할 수 없어요.")
        card.status = status
    db.commit()
    return card


def update_card(db: Session, user_id, card_id, daily_limit=None, overseas_enabled=None) -> dict:
    card = get_owned_card(db, user_id, card_id, lock=True)
    assert_allowed(db.get(Account, card.account_id), "MANAGE")
    if card.status not in ("ACTIVE", "SUSPENDED"):
        raise BankError("CARD_UNAVAILABLE", "사용할 수 없는 카드예요.")
    if daily_limit is not None:
        validate_limit(daily_limit)
        card.daily_limit = daily_limit
    if overseas_enabled is not None:
        card.overseas_enabled = overseas_enabled
    db.commit()
    return card_out(card)


def reissue(db: Session, user_id, card_id) -> dict:
    card = get_owned_card(db, user_id, card_id, lock=True)
    assert_allowed(db.get(Account, card.account_id), "MANAGE")
    if card.status not in ("ACTIVE", "SUSPENDED", "LOST"):
        raise BankError("CARD_UNAVAILABLE", "재발급할 수 없는 카드예요.")
    replacement = new_card(card.account_id, card.daily_limit, card.overseas_enabled, card.id)
    card.status = "REISSUED"
    db.add(replacement)
    db.commit()
    return card_out(replacement)


def payment_out(item: CardPayment) -> dict:
    return {k: getattr(item, k) for k in ("id", "card_id", "amount", "place", "category", "request_at", "complete_at")}


def payments(db: Session, user_id, card_id, month: str | None) -> list[dict]:
    get_owned_card(db, user_id, card_id)
    query = select(CardPayment).where(CardPayment.card_id == card_id)
    if month:
        try:
            year, m = map(int, month.split("-"))
            start = now_kst().replace(year=year, month=m, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=year + 1, month=1) if m == 12 else start.replace(month=m + 1)
        except ValueError:
            raise BankError("INVALID_TIME", "조회할 월을 확인해 주세요.")
        query = query.where(CardPayment.request_at >= start, CardPayment.request_at < end)
    return [payment_out(p) for p in db.scalars(query.order_by(CardPayment.request_at.desc(), CardPayment.id.desc()))]


def pay(db: Session, user_id, card_id, amount: int, place: str, category: str | None, overseas: bool) -> dict:
    try:
        if type(amount) is not int or amount <= 0:
            raise BankError("INVALID_AMOUNT", "결제 금액을 확인해 주세요.")
        card = get_owned_card(db, user_id, card_id, lock=True)
        account = db.get(Account, card.account_id)
        assert_allowed(account, "WITHDRAW")
        now = now_kst()
        expiry_month, expiry_year = map(int, card.expiry_date.split("/"))
        if card.status != "ACTIVE" or (2000 + expiry_year, expiry_month) < (now.year, now.month):
            raise BankError("CARD_UNAVAILABLE", "사용할 수 없는 카드예요.")
        if overseas and not card.overseas_enabled:
            raise BankError("OVERSEAS_BLOCKED", "해외결제가 꺼져 있어요.")
        spent = db.scalar(select(func.coalesce(func.sum(CardPayment.amount), 0)).where(CardPayment.card_id == card.id,
            CardPayment.complete_at >= now.replace(hour=0, minute=0, second=0, microsecond=0)))
        if spent + amount > card.daily_limit:
            raise BankError("CARD_LIMIT", "오늘 카드 사용한도를 넘어요.")
        if account.balance < amount:
            raise BankError("INSUFFICIENT", "계좌 잔액이 부족해요.")
        account.balance -= amount
        item = CardPayment(card_id=card.id, amount=amount, place=place, category=category, request_at=now, complete_at=now)
        db.add(item)
        db.flush()
        db.add(AccountTransaction(account_id=account.id, card_payment_id=item.id, transaction_type="CARD",
            transaction_direction="OUT", amount=amount, new_balance=account.balance, counterparty_name=place, transaction_at=now))
        notifications.create(db, user_id, "CARD_PAYMENT", f"{place}에서 {amount:,}원이 결제됐어요.")
        db.commit()
        return payment_out(item) | {"new_balance": account.balance}
    except Exception:
        db.rollback()
        raise
