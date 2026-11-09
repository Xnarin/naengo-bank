import csv
import io
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Account, AccountProduct, AccountTransaction, AutoTransfer, Base, Card, StatementRequest, Term, TermAgreement, User, VerificationCode, now_kst
from app.security import create_access_token, hash_secret, verify_secret
from app.services import accounts, mail
from app.services.transfers import transfer

PIN = "493827"


@pytest.fixture
def bank(monkeypatch):
    monkeypatch.setattr(settings, "development", True)
    monkeypatch.setattr(settings, "smtp_host", None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        secret = hash_secret(PIN)
        user = User(email="owner@example.com", user_name="소유자", password_hash=secret, pin=secret)
        other = User(email="other@example.com", user_name="다른분", password_hash=secret, pin=secret)
        product = AccountProduct(code="basic", product_name="입출금통장")
        db.add_all([user, other, product])
        db.flush()
        src = Account(user_id=user.id, product_id=product.id, account_num="111-1111-1111", account_password=secret, balance=2_000_000)
        mine = Account(user_id=user.id, product_id=product.id, account_num="222-2222-2222", account_password=secret)
        foreign = Account(user_id=other.id, product_id=product.id, account_num="333-3333-3333", account_password=secret)
        db.add_all([src, mine, foreign])
        db.add_all([Term(id=i, title=f"약관{i}", content="내용", version="1", category="ACCOUNT_OPEN", required=i != 3) for i in (1, 2, 3)])
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app, headers={"Authorization": "Bearer " + create_access_token(user.id)}) as http:
            yield http, db, user, src, mine, foreign
        app.dependency_overrides.clear()
    engine.dispose()


def open_body(**changes):
    return dict(product_code="basic", password="1234", password_confirm="1234", nickname="새통장",
                opening_info={"purpose": "생활비", "source": "급여"}, agreed_term_ids=[1, 2]) | changes


def add_tx(db, account, *, amount=1000, direction="IN", kind="DEPOSIT", name="회사", memo="월급", at=None):
    tx = AccountTransaction(account_id=account.id, transaction_type=kind, transaction_direction=direction,
        amount=amount, new_balance=account.balance, counterparty_name=name, memo=memo, transaction_at=at or now_kst())
    db.add(tx)
    db.commit()
    return tx


def test_open_account_and_terms(bank):
    http, db, user, *_ = bank
    response = http.post("/accounts", json=open_body())
    assert response.status_code == 201, response.text
    body = response.json()
    account = db.scalar(select(Account).where(Account.account_num == body["account_num"]))
    assert account.user_id == user.id and account.balance == 0
    assert account.daily_limit == 1_000_000 and account.month_limit == 5_000_000
    assert verify_secret(account.account_password, "1234")
    assert account.opening_info["purpose"] == "생활비"
    assert db.scalar(select(func.count()).select_from(TermAgreement)) == 3


@pytest.mark.parametrize("changes,code", [
    ({"agreed_term_ids": [1]}, "TERMS_REQUIRED"),
    ({"agreed_term_ids": [1, 2, 99]}, "TERMS_REQUIRED"),
    ({"password_confirm": "5678"}, "PASSWORD_MISMATCH"),
    ({"opening_info": {}}, "INVALID_ACCOUNT"),
    ({"product_code": "unknown"}, "INVALID_PRODUCT"),
])
def test_open_rejects_invalid_data_atomically(bank, changes, code):
    http, db, *_ = bank
    response = http.post("/accounts", json=open_body(**changes))
    assert response.json()["code"] == code
    assert db.scalar(select(func.count()).select_from(Account)) == 3
    assert db.scalar(select(func.count()).select_from(TermAgreement)) == 0


def test_account_number_collision_retries(bank, monkeypatch):
    http, db, _, src, *_ = bank
    numbers = iter([src.account_num, "444-4444-4444"])
    monkeypatch.setattr(accounts, "new_account_num", lambda _: next(numbers))
    response = http.post("/accounts", json=open_body())
    assert response.status_code == 201 and response.json()["account_num"] == "444-4444-4444"
    assert db.scalar(select(func.count()).select_from(TermAgreement)) == 3


def test_account_list_masks_sorts_and_separates_closed(bank):
    http, db, _, src, mine, _ = bank
    assert http.post(f"/accounts/{mine.id}/favorite").json() == {"is_favorite": True}
    items = http.get("/accounts").json()
    assert items[0]["id"] == str(mine.id) and len(items) == 2
    assert items[0]["account_num"] == "222-****-2222"
    assert http.get(f"/accounts/{mine.id}").json()["account_num"] == mine.account_num
    mine.status = "CLOSED"
    db.commit()
    assert len(http.get("/accounts").json()) == 1
    assert http.get("/accounts", params={"status": "closed"}).json()[0]["id"] == str(mine.id)


def test_all_account_endpoints_reject_other_users(bank):
    http, _, _, src, _, foreign = bank
    target = f"/accounts/{foreign.id}"
    for path in (target, target + "/transactions", target + "/transactions/1", target + "/close-check"):
        assert http.get(path).status_code == 404
    for suffix, data in (("favorite", None), ("unlock", {"code": "123456"}), ("close", {"pin": PIN}),
                         ("statements", {"from_date": "2026-01-01", "to_date": "2026-02-01", "email": "owner@example.com"})):
        assert http.post(target + "/" + suffix, json=data).status_code == 404
    assert http.put(target + "/limits", json={"daily_limit": 100, "month_limit": 100, "pin": PIN}).status_code == 404
    assert http.post("/pin/verify", json={"pin": PIN, "account_id": str(foreign.id)}).status_code == 404


def test_transaction_search_detail_and_calendar_defaults(bank):
    http, db, _, src, mine, _ = bank
    earlier = add_tx(db, src, amount=2000, at=now_kst() - timedelta(days=1))
    card = add_tx(db, src, amount=5000, direction="OUT", kind="CARD", name="카페", memo="커피")
    add_tx(db, src, amount=9000, name="100% 회사", at=now_kst() - timedelta(days=2))
    old = add_tx(db, src, at=now_kst() - timedelta(days=150))
    wrong = add_tx(db, mine)
    path = f"/accounts/{src.id}/transactions"
    assert len(http.get(path).json()) == 3
    for params in ({"direction": "OUT"}, {"type": "CARD"}, {"min": 3000, "max": 6000}, {"q": "커피"}, {"q": "카페"}, {"amount": 5000}):
        result = http.get(path, params=params).json()
        assert len(result) == 1 and result[0]["id"] == card.id
    assert len(http.get(path, params={"q": "%"}).json()) == 1
    assert http.get(path, params={"order": "asc"}).json()[-1]["id"] == card.id
    assert http.get(path + f"/{earlier.id}").json()["amount"] == 2000
    assert http.get(path + f"/{wrong.id}").status_code == 404
    assert len(http.get(path, params={"from": "2020-01-01", "to": "2099-01-01"}).json()) == 4
    assert http.get(path, params={"from": "2026-12-01", "to": "2026-01-01"}).json()["code"] == "INVALID_TIME"
    assert http.get(path, params={"min": 6000, "max": 3000}).json()["code"] == "INVALID_AMOUNT"
    assert accounts.date_range(None, date(2024, 5, 31))[0] == date(2024, 2, 29)


def test_usage_excludes_own_accounts_and_cards(bank):
    http, db, _, src, mine, foreign = bank
    transfer(db, src.id, mine.id, 1_200_000, "internal")
    transfer(db, src.id, foreign.id, 100_000, "external")
    add_tx(db, src, amount=5000, direction="OUT", kind="CARD")
    result = http.get(f"/accounts/{src.id}").json()
    assert result["today_used"] == result["month_used"] == 100_000


@pytest.mark.parametrize("daily,monthly", [(0, 100), (10_000_001, 50_000_000), (100, 50_000_001), (200, 100)])
def test_limits_reject_invalid_values(bank, daily, monthly):
    http, _, _, src, *_ = bank
    response = http.put(f"/accounts/{src.id}/limits", json={"daily_limit": daily, "month_limit": monthly, "pin": PIN})
    assert response.json()["code"] == "INVALID_LIMIT"


def test_limits_pin_suspension_and_unlock_consumption(bank):
    http, db, user, src, mine, _ = bank
    path = f"/accounts/{src.id}"
    for i in range(5):
        response = http.put(path + "/limits", json={"daily_limit": 200_000, "month_limit": 500_000, "pin": "000000"})
        assert response.status_code == (403 if i == 4 else 401)
    assert src.status == "SUSPENDED" and user.status == "ACTIVE" and src.daily_limit == 1_000_000
    assert http.get(path).status_code == 200
    assert http.post(path + "/favorite").json()["code"] == "SUSPENDED"
    assert http.post(path + "/unlock", json={"code": "123456"}).status_code == 400
    code = VerificationCode(email=user.email, purpose="UNLOCK_ACCOUNT", code_hash=hash_secret("123456"), expires_at=now_kst() + timedelta(minutes=3))
    db.add(code)
    db.commit()
    assert http.post(path + "/unlock", json={"code": "123456"}).json()["status"] == "ACTIVE"
    mine.status = "SUSPENDED"
    db.commit()
    assert http.post(f"/accounts/{mine.id}/unlock", json={"code": "123456"}).status_code == 400
    response = http.put(path + "/limits", json={"daily_limit": 200_000, "month_limit": 500_000, "pin": PIN})
    assert response.status_code == 200 and response.json()["daily_limit"] == 200_000


def test_close_blockers_and_history_preserved(bank):
    http, db, _, src, mine, foreign = bank
    db.add(Card(account_id=mine.id, card_number="encrypted-test-placeholder", expiry_date="01/30", status="LOST"))
    db.add(AutoTransfer(from_account_id=mine.id, to_account_id=foreign.id, amount=100, cycle="ONCE", start_date=now_kst().date(), next_run_at=now_kst()))
    db.commit()
    result = http.get(f"/accounts/{mine.id}/close-check").json()
    assert not result["closable"] and {x["kind"] for x in result["blockers"]} == {"card", "auto_transfer"}
    assert http.post(f"/accounts/{mine.id}/close", json={"pin": PIN}).json()["code"] == "CLOSE_BLOCKED"
    assert http.get(f"/accounts/{src.id}/close-check").json()["blockers"][0]["kind"] == "balance"
    db.scalar(select(Card)).status = "CANCELED"
    db.scalar(select(AutoTransfer)).status = "CANCELED"
    tx = add_tx(db, mine)
    assert http.post(f"/accounts/{mine.id}/close", json={"pin": "000000"}).status_code == 401
    assert http.post(f"/accounts/{mine.id}/close", json={"pin": PIN}).json()["status"] == "CLOSED"
    assert mine.closed_at and not mine.is_favorite
    assert http.get(f"/accounts/{mine.id}/transactions/{tx.id}").status_code == 200
    assert http.post(f"/accounts/{mine.id}/close", json={"pin": PIN}).status_code == 400
    for _ in range(5):
        assert http.post("/pin/verify", json={"pin": "000000", "account_id": str(mine.id)}).status_code == 400
    assert mine.status == "CLOSED"
    assert http.post(f"/accounts/{mine.id}/favorite").status_code == 400


def test_statement_csv_and_delivery_status(bank, monkeypatch):
    http, db, _, src, *_ = bank
    add_tx(db, src, name="=HYPERLINK(1)", memo="  +SUM(1)")
    sent = []
    def send(*args, **kwargs):
        sent.append((args, kwargs))
        return True
    monkeypatch.setattr(mail, "send_mail", send)
    today = now_kst().date().isoformat()
    body = {"from_date": today, "to_date": today, "email": "owner@example.com"}
    path = f"/accounts/{src.id}/statements"
    rejected = http.post(path, json=body | {"email": "other@example.com"})
    assert rejected.status_code == 403 and rejected.json()["code"] == "STATEMENT_RECIPIENT"
    assert sent == [] and db.scalar(select(func.count()).select_from(StatementRequest)) == 0
    response = http.post(path, json=body)
    assert response.status_code == 202 and response.json()["status"] == "SENT"
    attachment = sent[0][1]["attachment"]
    rows = list(csv.reader(io.StringIO(attachment[1].decode("utf-8-sig"))))
    assert rows[1][5].startswith("'=") and rows[1][7].startswith("'")
    assert len(rows) == 2
    def fail(*args, **kwargs):
        raise OSError("mail failure")
    monkeypatch.setattr(mail, "send_mail", fail)
    assert http.post(path, json=body).json()["status"] == "FAILED"
    assert db.scalars(select(StatementRequest).order_by(StatementRequest.id)).all()[-1].status == "FAILED"
    assert http.post(path, json=body | {"from_date": "2099-01-01"}).status_code == 400


def test_mail_builds_csv_attachment(bank, monkeypatch):
    messages = []
    class SMTP:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def starttls(self): pass
        def login(self, *args): pass
        def send_message(self, message): messages.append(message)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "내금고 <sender@example.com>")
    monkeypatch.setattr(mail.smtplib, "SMTP", SMTP)
    payload = "날짜,금액\n2026-11-05,1000".encode("utf-8-sig")
    assert mail.send_mail("owner@example.com", "거래내역", "첨부", attachment=("transactions.csv", payload))
    attachment = list(messages[0].iter_attachments())[0]
    assert attachment.get_filename() == "transactions.csv" and attachment.get_payload(decode=True) == payload
