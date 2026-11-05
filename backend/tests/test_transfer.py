"""이체 공통 함수 검사. SQLite 메모리 DB라 PostgreSQL 없이 돈다 (행 잠금 동시성은 검사 범위 밖)."""
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.errors import BankError
from app.models import Account, AccountProduct, AccountTransaction, Base, Notification, User
from app.services import notifications
from app.services.transfers import transfer

U1, U2, A1, A2 = (uuid.uuid4() for _ in range(4))


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        s.add(AccountProduct(id=1, code="basic", product_name="내금고 입출금통장"))
        for uid, name, i in [(U1, "홍길동", 1), (U2, "김철수", 2)]:
            s.add(User(id=uid, email=f"u{i}@test.com", password_hash="x", pin="x", user_name=name))
        s.add_all([
            Account(id=A1, user_id=U1, product_id=1, account_num="111-1111-1111", account_password="x", balance=2_000_000),
            Account(id=A2, user_id=U2, product_id=1, account_num="222-2222-2222", account_password="x", balance=0),
        ])
        s.commit()
        yield s


def balances(db):
    return [db.get(Account, i).balance for i in (A1, A2)]


def test_success_writes_two_ledger_rows(db):
    t = transfer(db, A1, A2, 50_000, "k1", memo="용돈")
    assert balances(db) == [1_950_000, 50_000]
    rows = db.scalars(select(AccountTransaction).where(AccountTransaction.transfer_id == t.id)).all()
    assert sorted((r.transaction_direction, r.new_balance, r.counterparty_name) for r in rows) == [
        ("IN", 50_000, "홍길동"), ("OUT", 1_950_000, "김철수")]


def test_idempotent(db):
    a = transfer(db, A1, A2, 10_000, "same")
    b = transfer(db, A1, A2, 10_000, "same")
    assert a.id == b.id and balances(db) == [1_990_000, 10_000]
    notices = db.scalars(select(Notification)).all()
    assert len(notices) == 1 and notices[0].user_id == U2
    assert notices[0].type == "TRANSFER_IN" and "홍길동" in notices[0].message and "10,000원" in notices[0].message


@pytest.mark.parametrize("amount", [True, 1.0, 1.5, "1000"])
def test_service_rejects_non_integer_amount(db, amount):
    with pytest.raises(BankError) as e:
        transfer(db, A1, A2, amount, "bad-amount")
    assert e.value.code == "INVALID_AMOUNT" and balances(db) == [2_000_000, 0]


@pytest.mark.parametrize("amount,code", [
    (0, "INVALID_AMOUNT"),
    (1_000_001, "LIMIT"),
])
def test_rejects(db, amount, code):
    with pytest.raises(BankError) as e:
        transfer(db, A1, A2, amount, "k")
    assert e.value.code == code and balances(db) == [2_000_000, 0]


def test_daily_limit_is_cumulative(db):
    transfer(db, A1, A2, 600_000, "a")
    with pytest.raises(BankError, match="1일") as e:
        transfer(db, A1, A2, 500_000, "b")
    assert "400,000원" in e.value.message  # 남은 한도 안내
    assert balances(db) == [1_400_000, 600_000]


def test_insufficient_balance(db):
    with pytest.raises(BankError) as e:
        transfer(db, A2, A1, 1, "k")
    assert e.value.code == "INSUFFICIENT"
    assert db.scalars(select(Notification)).all() == []


def test_own_account_transfer_does_not_notify_incoming(db):
    db.get(Account, A2).user_id = U1
    db.commit()
    transfer(db, A1, A2, 10_000, "own")
    assert balances(db) == [1_990_000, 10_000]
    assert db.scalars(select(Notification)).all() == []


def test_notification_failure_rolls_back_transfer(db, monkeypatch):
    def fail(*args):
        raise RuntimeError("notification failed")
    monkeypatch.setattr(notifications, "create", fail)
    with pytest.raises(RuntimeError):
        transfer(db, A1, A2, 10_000, "rollback")
    assert balances(db) == [2_000_000, 0]
    assert db.scalars(select(AccountTransaction)).all() == []
    assert db.scalars(select(Notification)).all() == []


@pytest.mark.parametrize("status,who,code", [
    ("SUSPENDED", "src", "SUSPENDED"),
    ("CLOSED", "src", "INVALID_FROM"),
    ("SUSPENDED", "dst", "INVALID_ACCOUNT"),
    ("CLOSED", "dst", "INVALID_ACCOUNT"),
])
def test_blocked_status(db, status, who, code):
    db.get(Account, A1 if who == "src" else A2).status = status
    db.commit()
    with pytest.raises(BankError) as e:
        transfer(db, A1, A2, 1_000, "k")
    assert e.value.code == code and balances(db) == [2_000_000, 0]
