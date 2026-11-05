"""이체 공통 함수. 즉시이체 API, 자동이체 스케줄러, AI Agent가 모두 이것만 호출한다."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import Account, AccountTransaction, FavoriteRecipient, Transfer, User, now_kst
from app.security import verify_pin
from app.services import notifications
from app.services.accounts import account_usage, assert_allowed, get_owned_account, mask_name


def same_request(done: Transfer, from_id, to_id, amount, memo, auto_id) -> Transfer:
    if (done.from_account_id, done.to_account_id, done.amount, done.memo, done.auto_transfer_id) != (from_id, to_id, amount, memo, auto_id):
        raise BankError("INVALID_AMOUNT", "이미 사용한 요청 번호예요. 원래 이체 결과를 확인하거나 새 요청 번호를 사용해 주세요.", 409)
    return done


def check_limits(db: Session, src: Account, amount: int) -> None:
    usage = account_usage(db, src)
    today = usage["today_used"]
    if today + amount > src.daily_limit:
        raise BankError("LIMIT", f"1일 이체한도를 넘어요. 오늘 {src.daily_limit - today:,}원까지 보낼 수 있어요.")
    month = usage["month_used"]
    if month + amount > src.month_limit:
        raise BankError("LIMIT", f"1달 이체한도를 넘어요. 이번 달 {src.month_limit - month:,}원까지 보낼 수 있어요.")


def transfer(
    db: Session,
    from_account_id: uuid.UUID,
    to_account_id: uuid.UUID,
    amount: int,
    idempotency_key: str,
    memo: str | None = None,
    auto_transfer_id: uuid.UUID | None = None,
    *,
    commit: bool = True,
) -> Transfer:
    """기본은 성공 commit·실패 rollback. commit=False는 호출자가 트랜잭션/저장점을 관리한다.

    같은 idempotency_key는 한 번만 실행된다. 스케줄러는 회차 기록까지 같은 트랜잭션으로 묶는다.
    """
    try:
        if type(amount) is not int or amount <= 0:
            raise BankError("INVALID_AMOUNT", "송금 금액을 확인해 주세요.")
        done = db.scalar(select(Transfer).where(Transfer.idempotency_key == idempotency_key))
        if done:
            return same_request(done, from_account_id, to_account_id, amount, memo, auto_transfer_id)
        if from_account_id == to_account_id:
            raise BankError("SAME_ACCOUNT", "출금 계좌와 같은 계좌로는 보낼 수 없어요.")

        # 데드락 방지: 항상 id 오름차순으로 잠금. populate_existing 으로 세션에 남은 옛 잔액을 덮어씀
        rows = db.scalars(
            select(Account)
            .where(Account.id.in_((from_account_id, to_account_id)))
            .order_by(Account.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        accounts = {a.id: a for a in rows}
        # 같은 계좌의 중복 요청이 잠금을 기다리는 동안 먼저 처리됐을 수 있다.
        done = db.scalar(select(Transfer).where(Transfer.idempotency_key == idempotency_key))
        if done:
            return same_request(done, from_account_id, to_account_id, amount, memo, auto_transfer_id)
        if from_account_id not in accounts:
            raise BankError("INVALID_FROM", "출금 계좌를 찾을 수 없어요.", 404)
        if to_account_id not in accounts:
            raise BankError("INVALID_ACCOUNT", "존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요.", 404)
        src, dst = accounts[from_account_id], accounts[to_account_id]

        assert_allowed(src, "WITHDRAW")
        if dst.status != "ACTIVE":
            raise BankError("INVALID_ACCOUNT", "받을 수 없는 계좌예요(거래중지 또는 해지). 받는 분께 확인해 주세요.")
        if src.user_id != dst.user_id:
            check_limits(db, src, amount)
        if src.balance < amount:
            raise BankError("INSUFFICIENT", f"잔액이 부족해요. 출금 가능 금액은 {src.balance:,}원이에요.")

        src.balance -= amount
        dst.balance += amount
        now = now_kst()
        tx_type = "AUTO_TRANSFER" if auto_transfer_id else "TRANSFER"
        t = Transfer(
            idempotency_key=idempotency_key, from_account_id=src.id, to_account_id=dst.id,
            amount=amount, memo=memo, status="SUCCESS", auto_transfer_id=auto_transfer_id,
            request_at=now, complete_at=now,
        )
        db.add(t)
        db.flush()
        src_name, dst_name = (db.get(User, a.user_id).user_name for a in (src, dst))
        db.add_all([
            AccountTransaction(account_id=src.id, transaction_type=tx_type, transaction_direction="OUT", amount=amount,
                               new_balance=src.balance, counterparty_name=dst_name, counterparty_account=dst.account_num,
                               memo=memo, transfer_id=t.id, transaction_at=now),
            AccountTransaction(account_id=dst.id, transaction_type=tx_type, transaction_direction="IN", amount=amount,
                               new_balance=dst.balance, counterparty_name=src_name, counterparty_account=src.account_num,
                               memo=memo, transfer_id=t.id, transaction_at=now),
        ])
        if src.user_id != dst.user_id:
            notifications.create(db, dst.user_id, "TRANSFER_IN", f"{src_name}님이 {amount:,}원을 보냈어요.")
        if auto_transfer_id:
            notifications.create(db, src.user_id, "AUTO_TRANSFER_SUCCESS", f"자동·예약이체로 {dst_name}님께 {amount:,}원을 보냈어요.")
        if commit:
            db.commit()
        else:
            db.flush()
        return t
    except IntegrityError:
        if not commit:
            raise
        db.rollback()
        # 서로 다른 계좌 쌍이 같은 키로 동시에 실행돼도 출금·원장은 함께 되돌린다.
        done = db.scalar(select(Transfer).where(Transfer.idempotency_key == idempotency_key))
        if done:
            return same_request(done, from_account_id, to_account_id, amount, memo, auto_transfer_id)
        raise
    except Exception:
        if commit:
            db.rollback()
        raise


def find_recipient(db: Session, account_num: str) -> Account:
    account = db.scalar(select(Account).where(Account.account_num == account_num))
    if account is None:
        raise BankError("INVALID_ACCOUNT", "존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요.", 404)
    if account.status != "ACTIVE":
        raise BankError("INVALID_ACCOUNT", "받을 수 없는 계좌예요(거래중지 또는 해지). 받는 분께 확인해 주세요.")
    return account


def recipient_name(db: Session, account: Account, user_id: uuid.UUID) -> str:
    owner = db.get(User, account.user_id)
    return (account.nickname or owner.user_name) if account.user_id == user_id else mask_name(owner.user_name)


def check_recipient(db: Session, user_id: uuid.UUID, account_num: str) -> dict:
    account = find_recipient(db, account_num)
    return {"account_num": account.account_num, "holder_name": recipient_name(db, account, user_id), "mine": account.user_id == user_id}


def transfer_out(db: Session, item: Transfer, user_id: uuid.UUID) -> dict:
    destination = db.get(Account, item.to_account_id)
    outgoing = db.scalar(select(AccountTransaction).where(AccountTransaction.transfer_id == item.id,
        AccountTransaction.account_id == item.from_account_id, AccountTransaction.transaction_direction == "OUT"))
    return {"transfer_id": item.id, "status": item.status, "amount": item.amount,
            "to_name": recipient_name(db, destination, user_id), "to_account_num": destination.account_num,
            "new_balance": outgoing.new_balance if outgoing else None}


def get_by_key(db: Session, user_id: uuid.UUID, key: str) -> dict:
    item = db.scalar(select(Transfer).join(Account, Transfer.from_account_id == Account.id)
        .where(Transfer.idempotency_key == f"user:{user_id}:{key}", Account.user_id == user_id))
    if item is None:
        raise BankError("INVALID_ACCOUNT", "이체 결과를 찾을 수 없어요.", 404)
    return transfer_out(db, item, user_id)


def create_transfer(db: Session, user: User, *, from_account_id: uuid.UUID, to_account_num: str,
                    amount: int, memo: str | None, pin: str, idempotency_key: str) -> dict:
    source = get_owned_account(db, user.id, from_account_id)
    # 완료된 요청은 계좌 상태가 바뀌어도 원래 결과를 재조회할 수 있다.
    destination = db.scalar(select(Account).where(Account.account_num == to_account_num))
    if destination is None:
        raise BankError("INVALID_ACCOUNT", "존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요.", 404)
    verify_pin(db, user, pin, account=source)
    item = transfer(db, source.id, destination.id, amount, f"user:{user.id}:{idempotency_key}", memo)
    return transfer_out(db, item, user.id)


def recent_recipients(db: Session, user_id: uuid.UUID) -> list[dict]:
    recent = (select(Transfer.to_account_id.label("account_id"), func.max(Transfer.complete_at).label("last_sent_at"))
        .join(Account, Transfer.from_account_id == Account.id)
        .where(Account.user_id == user_id, Transfer.status == "SUCCESS")
        .group_by(Transfer.to_account_id).subquery())
    rows = db.execute(select(Account, recent.c.last_sent_at).join(recent, Account.id == recent.c.account_id)
        .order_by(recent.c.last_sent_at.desc(), Account.id).limit(10))
    return [{"account_num": a.account_num, "holder_name": recipient_name(db, a, user_id), "last_sent_at": at} for a, at in rows]


def favorite_out(item: FavoriteRecipient) -> dict:
    return {"id": item.id, "account_num": item.account_num, "holder_name": mask_name(item.holder_name), "alias": item.alias}


def list_favorites(db: Session, user_id: uuid.UUID) -> list[dict]:
    return [favorite_out(item) for item in db.scalars(select(FavoriteRecipient).where(FavoriteRecipient.user_id == user_id).order_by(FavoriteRecipient.id))]


def add_favorite(db: Session, user_id: uuid.UUID, account_num: str, alias: str | None) -> dict:
    # 같은 회원의 중복 등록을 직렬화한다 (기존 스키마에는 복합 UNIQUE가 없다).
    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요.", 401)
    account = find_recipient(db, account_num)
    item = db.scalar(select(FavoriteRecipient).where(FavoriteRecipient.user_id == user_id, FavoriteRecipient.account_num == account_num))
    if item is None:
        item = FavoriteRecipient(user_id=user_id, account_num=account_num, holder_name=db.get(User, account.user_id).user_name, alias=alias)
        db.add(item)
    else:
        item.alias = alias
    db.commit()
    return favorite_out(item)


def get_favorite(db: Session, user_id: uuid.UUID, item_id: int) -> FavoriteRecipient:
    item = db.scalar(select(FavoriteRecipient).where(FavoriteRecipient.id == item_id, FavoriteRecipient.user_id == user_id).with_for_update())
    if item is None:
        raise BankError("INVALID_ACCOUNT", "즐겨찾는 계좌를 찾을 수 없어요.", 404)
    return item


def update_favorite(db: Session, user_id: uuid.UUID, item_id: int, alias: str | None) -> dict:
    item = get_favorite(db, user_id, item_id)
    item.alias = alias
    db.commit()
    return favorite_out(item)


def delete_favorite(db: Session, user_id: uuid.UUID, item_id: int) -> None:
    db.delete(get_favorite(db, user_id, item_id))
    db.commit()
