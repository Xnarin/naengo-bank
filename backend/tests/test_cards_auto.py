import uuid
from datetime import date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import auto_transfers as auto_api, cards as card_api, notifications as notification_api
from app.config import settings
from app.db import get_db
from app.errors import BankError
from app.models import KST, Account, AccountProduct, AccountTransaction, AutoTransfer, Base, Card, CardPayment, Notification, Transfer, User, now_kst
from app.security import create_access_token, hash_secret
from app.services import auto_transfers, cards, notifications

PIN = "493827"


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.setattr(settings, "card_key", Fernet.generate_key().decode())
    app = FastAPI()
    for router in (auto_api.router, card_api.router, notification_api.router):
        app.include_router(router)
    @app.exception_handler(BankError)
    def error(_, e):
        return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)
    # SQLite의 구형 자동 트랜잭션 모드는 SAVEPOINT 해제를 실제 commit으로 취급할 수 있다.
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False, "autocommit": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def fk(connection, _):
        connection.autocommit = True
        connection.execute("PRAGMA foreign_keys=ON")
        connection.autocommit = False
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        secret = hash_secret(PIN)
        user = User(email="sender@example.com", user_name="소유자", password_hash=secret, pin=secret)
        other = User(email="other@example.com", user_name="홍길동", password_hash=secret, pin=secret)
        product = AccountProduct(code="basic", product_name="입출금통장")
        db.add_all([user, other, product])
        db.flush()
        source = Account(user_id=user.id, product_id=product.id, account_num="111-1111-1111", account_password=secret, balance=2_000_000)
        target = Account(user_id=other.id, product_id=product.id, account_num="222-2222-2222", account_password=secret)
        db.add_all([source, target])
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app, headers={"Authorization": "Bearer " + create_access_token(user.id)}) as http:
            yield http, db, user, source, target, other
    engine.dispose()


def issue(http, account, **changes):
    response = http.post("/cards", json={"account_id": str(account.id), "daily_limit": 100_000, "overseas_enabled": False} | changes)
    assert response.status_code == 201, response.text
    return response.json()


def schedule_body(source, target, **changes):
    return {"from_account_id": str(source.id), "to_account_num": target.account_num, "amount": 10_000,
        "pin": PIN, "cycle": "ONCE", "run_at": (now_kst() + timedelta(minutes=5)).isoformat()} | changes


def register(http, source, target, **changes):
    response = http.post("/auto-transfers", json=schedule_body(source, target, **changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_card_issue_encryption_luhn_ownership_and_duplicate(bank):
    http, db, _, source, _, other = bank
    first = issue(http, source)
    stored = db.get(Card, uuid.UUID(first["id"]))
    raw = Fernet(settings.card_key.encode()).decrypt(stored.card_number.encode()).decode()
    digits = [int(x) for x in raw]
    checksum = sum((x * 2 - 9 if x * 2 > 9 else x * 2) if i % 2 == 0 else x for i, x in enumerate(digits))
    assert len(raw) == 16 and checksum % 10 == 0
    assert raw not in str(first) and first["last4"] == raw[-4:] and stored.card_number != raw
    assert http.post("/cards", json={"account_id": str(source.id)}).status_code == 409
    assert http.get("/cards").json()[0]["last4"] == raw[-4:]
    http.headers["Authorization"] = "Bearer " + create_access_token(other.id)
    assert http.get("/cards").json() == []
    assert http.get("/cards/" + first["id"]).status_code == 404
    assert http.post("/cards/" + first["id"] + "/lost", json={"pin": PIN}).status_code == 404


def test_card_lost_suspend_reissue_and_cancel(bank):
    http, db, _, source, *_ = bank
    original = issue(http, source)
    path = "/cards/" + original["id"]
    assert http.post(path + "/suspend", json={"pin": PIN}).json()["status"] == "SUSPENDED"
    assert http.post(path + "/resume", json={"pin": PIN}).json()["status"] == "ACTIVE"
    assert http.post(path + "/lost", json={"pin": PIN}).json()["status"] == "LOST"
    assert http.post(path + "/resume", json={"pin": PIN}).status_code == 400
    response = http.post(path + "/reissue", json={"pin": PIN})
    assert response.status_code == 201
    replacement = db.get(Card, uuid.UUID(response.json()["id"]))
    assert replacement.reissued_from_id == uuid.UUID(original["id"])
    assert db.get(Card, uuid.UUID(original["id"])).status == "REISSUED"
    assert http.post(path + "/reissue", json={"pin": PIN}).status_code == 400
    assert http.post("/cards/" + str(replacement.id) + "/cancel", json={"pin": PIN}).json()["status"] == "CANCELED"
    assert http.post("/cards/" + str(replacement.id) + "/resume", json={"pin": PIN}).status_code == 400
    assert issue(http, source)["status"] == "ACTIVE"


def test_card_payments_ledger_limits_overseas_and_notifications(bank):
    http, db, user, source, *_ = bank
    card = issue(http, source)
    path = "/cards/" + card["id"]
    payment = {"amount": 50_000, "place": "카페", "category": "카페"}
    response = http.post(path + "/payments", json=payment)
    assert response.status_code == 201 and response.json()["new_balance"] == 1_950_000
    row = db.scalar(select(AccountTransaction))
    assert row.transaction_type == "CARD" and row.card_payment_id == response.json()["id"]
    assert http.post(path + "/payments", json=payment | {"amount": 60_000}).json()["code"] == "CARD_LIMIT"
    assert http.post(path + "/payments", json=payment | {"overseas": True}).json()["code"] == "OVERSEAS_BLOCKED"
    assert db.scalar(select(func.count()).select_from(CardPayment)) == 1
    assert http.patch(path, json={"daily_limit": 200_000, "overseas_enabled": True, "pin": PIN}).status_code == 200
    assert http.post(path + "/payments", json=payment | {"overseas": True}).status_code == 201
    assert len(http.get(path + "/payments", params={"month": now_kst().strftime("%Y-%m")}).json()) == 2
    assert http.get(path + "/payments", params={"month": "2026-13"}).status_code == 400
    assert http.get("/notifications").json()["unread"] == 2
    assert http.post("/notifications/read-all").status_code == 204
    assert http.get("/notifications").json()["unread"] == 0
    assert db.get(Account, source.id).balance == 1_900_000


@pytest.mark.parametrize("status", ["SUSPENDED", "LOST", "REISSUED", "CANCELED"])
def test_unusable_cards_never_charge(bank, status):
    http, db, _, source, *_ = bank
    card = issue(http, source)
    db.get(Card, uuid.UUID(card["id"])).status = status
    db.commit()
    response = http.post("/cards/" + card["id"] + "/payments", json={"amount": 1000, "place": "가맹점"})
    assert response.json()["code"] == "CARD_UNAVAILABLE"
    assert db.get(Account, source.id).balance == 2_000_000
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 0


def test_suspended_account_and_low_balance_never_charge(bank):
    http, db, _, source, *_ = bank
    card = issue(http, source)
    source.status = "SUSPENDED"
    db.commit()
    path = "/cards/" + card["id"] + "/payments"
    assert http.post(path, json={"amount": 1000, "place": "가맹점"}).json()["code"] == "SUSPENDED"
    source.status, source.balance = "ACTIVE", 0
    db.commit()
    assert http.post(path, json={"amount": 1000, "place": "가맹점"}).json()["code"] == "INSUFFICIENT"
    assert db.scalar(select(func.count()).select_from(CardPayment)) == 0


def test_notification_read_is_scoped_to_owner(bank):
    http, db, user, _, _, other = bank
    notifications.create(db, user.id, "CARD_PAYMENT", "mine")
    notifications.create(db, other.id, "SUSPICIOUS_LOGIN", "other")
    db.commit()
    assert len(http.get("/notifications").json()["items"]) == 1
    assert http.post("/notifications/read-all").status_code == 204
    other_notice = db.scalar(select(Notification).where(Notification.user_id == other.id))
    assert other_notice.read_at is None


def test_once_execution_is_atomic_and_idempotent(bank):
    http, db, _, source, target, other = bank
    result = register(http, source, target)
    schedule_id = uuid.UUID(result["id"])
    at = datetime.fromisoformat(result["next_run_at"]) + timedelta(seconds=1)
    assert auto_transfers.process_one(db, schedule_id, at)
    assert not auto_transfers.process_one(db, schedule_id, at)
    assert db.get(Account, source.id).balance == 1_990_000 and db.get(Account, target.id).balance == 10_000
    assert db.scalar(select(func.count()).select_from(Transfer)) == 1
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 2
    assert http.get("/auto-transfers").json()[0]["last_run"]["status"] == "SUCCESS"
    assert http.get("/auto-transfers", params={"status": "ACTIVE"}).json() == []
    http.headers["Authorization"] = "Bearer " + create_access_token(other.id)
    assert http.get("/auto-transfers").json() == []
    assert http.delete("/auto-transfers/" + str(schedule_id)).status_code == 404


def test_failed_once_has_no_ledger_and_one_notification(bank):
    http, db, _, source, target, _ = bank
    source.balance = 0
    db.commit()
    result = register(http, source, target)
    schedule_id = uuid.UUID(result["id"])
    at = datetime.fromisoformat(result["next_run_at"]) + timedelta(seconds=1)
    assert auto_transfers.process_one(db, schedule_id, at)
    assert not auto_transfers.process_one(db, schedule_id, at)
    assert db.scalar(select(Transfer)).status == "FAILED"
    assert db.scalar(select(AutoTransfer)).status == "ENDED"
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 0
    assert http.get("/notifications").json()["unread"] == 1


def test_cancel_and_invalid_schedule_requests(bank):
    http, db, _, source, target, other = bank
    result = register(http, source, target)
    assert http.delete("/auto-transfers/" + result["id"]).status_code == 204
    assert not auto_transfers.process_one(db, uuid.UUID(result["id"]), datetime.fromisoformat(result["next_run_at"]) + timedelta(days=1))
    invalid = [
        {"run_at": (now_kst() - timedelta(minutes=1)).isoformat()},
        {"run_at": "2028-01-01T09:00:00"},
        {"cycle": "WEEKLY", "run_day": 7, "run_at": None},
        {"cycle": "MONTHLY", "run_day": 0, "run_at": None},
        {"to_account_num": source.account_num},
        {"pin": "000000"},
        {"from_account_id": str(target.id)},
    ]
    for changes in invalid:
        assert http.post("/auto-transfers", json=schedule_body(source, target, **changes)).status_code in (400, 401, 404)
    assert db.scalar(select(func.count()).select_from(AutoTransfer)) == 1


def test_month_end_weekly_and_end_date():
    jan31 = datetime(2028, 1, 31, 9, tzinfo=KST)
    feb = auto_transfers.next_run("MONTHLY", 31, date(2028, 1, 1), None, jan31)
    assert feb == datetime(2028, 2, 29, 9, tzinfo=KST)
    assert auto_transfers.next_run("MONTHLY", 31, date(2028, 1, 1), None, feb) == datetime(2028, 3, 31, 9, tzinfo=KST)
    assert auto_transfers.next_run("MONTHLY", 31, date(2028, 1, 1), date(2028, 2, 28), jan31) is None
    monday = datetime(2028, 1, 3, 9, tzinfo=KST)
    assert auto_transfers.next_run("WEEKLY", 0, date(2028, 1, 1), None, monday) == monday + timedelta(days=7)


def test_recurrence_failure_advances_and_rollback_keeps_money(bank, monkeypatch):
    http, db, _, source, target, _ = bank
    result = register(http, source, target, cycle="MONTHLY", run_day=31, run_at=None)
    schedule_id = uuid.UUID(result["id"])
    at = datetime.fromisoformat(result["next_run_at"]) + timedelta(seconds=1)
    original = auto_transfers.next_run
    def fail(*args, **kwargs):
        raise RuntimeError("state update failed")
    monkeypatch.setattr(auto_transfers, "next_run", fail)
    with pytest.raises(RuntimeError):
        auto_transfers.process_one(db, schedule_id, at)
    db.rollback()
    assert db.get(Account, source.id).balance == 2_000_000
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0
    monkeypatch.setattr(auto_transfers, "next_run", original)
    source = db.get(Account, source.id)
    source.balance = 0
    db.commit()
    assert auto_transfers.process_one(db, schedule_id, at)
    row = db.get(AutoTransfer, schedule_id)
    assert row.status == "ACTIVE"
    assert auto_transfers.aware(row.next_run_at) > at


def test_runner_processes_due_only(bank):
    from app.scheduler import run_due
    from sqlalchemy.orm import sessionmaker
    http, db, _, source, target, _ = bank
    first = register(http, source, target)
    second = register(http, source, target, run_at=(now_kst() + timedelta(days=5)).isoformat())
    run_due(sessionmaker(db.get_bind(), expire_on_commit=False), datetime.fromisoformat(first["next_run_at"]) + timedelta(seconds=1))
    db.expire_all()
    assert db.get(AutoTransfer, uuid.UUID(first["id"])).status == "ENDED"
    assert db.get(AutoTransfer, uuid.UUID(second["id"])).status == "ACTIVE"


def test_expired_card_and_expired_schedule_do_not_pay(bank):
    http, db, _, source, target, _ = bank
    card = issue(http, source)
    db.get(Card, uuid.UUID(card["id"])).expiry_date = "01/20"
    db.commit()
    assert http.post("/cards/" + card["id"] + "/payments", json={"amount": 1000, "place": "가맹점"}).json()["code"] == "CARD_UNAVAILABLE"
    result = register(http, source, target, end_date=(now_kst() + timedelta(days=1)).date().isoformat())
    row = db.get(AutoTransfer, uuid.UUID(result["id"]))
    assert not auto_transfers.process_one(db, row.id, now_kst() + timedelta(days=3))
    assert row.status == "ENDED"
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 0


def test_payment_rolls_back_if_notification_fails(bank, monkeypatch):
    http, db, _, source, *_ = bank
    card = issue(http, source)
    def fail(*args, **kwargs):
        raise RuntimeError("notification write failed")
    monkeypatch.setattr(notifications, "create", fail)
    with pytest.raises(RuntimeError):
        http.post("/cards/" + card["id"] + "/payments", json={"amount": 1000, "place": "가맹점"})
    assert db.get(Account, source.id).balance == 2_000_000
    assert db.scalar(select(func.count()).select_from(CardPayment)) == 0
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 0


def test_scheduler_runs_callback_and_shuts_down():
    import threading
    from app.scheduler import create_scheduler
    fired = threading.Event()
    scheduler = create_scheduler()
    scheduler.get_jobs()[0].modify(func=lambda: fired.set())
    scheduler.start()
    try:
        assert fired.wait(5)
    finally:
        scheduler.shutdown(wait=True)
    assert not scheduler.running
