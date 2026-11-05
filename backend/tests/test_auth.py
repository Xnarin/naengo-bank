from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Account, AccountProduct, AccountTransaction, Base, LoginHistory, Notification, Term, TermAgreement, User, VerificationCode, now_kst
from app.security import create_access_token, hash_secret, verify_pin, verify_secret
from app.errors import BankError
from app.services import auth, verification

EMAIL = "member@example.com"
PASSWORD = "Password123!"
PIN = "493827"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "development", True)
    monkeypatch.setattr(settings, "smtp_host", None)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add(AccountProduct(code="basic", product_name="입출금통장"))
        db.add_all([Term(id=i, title=f"약관{i}", content="내용", version="1", category="SIGNUP", required=i < 3)
                    for i in range(1, 4)])
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as http:
            yield http, db
        app.dependency_overrides.clear()
    engine.dispose()


def request_code(http, purpose="SIGNUP", email=EMAIL):
    r = http.post("/auth/codes", json={"email": email, "purpose": purpose})
    assert r.status_code == 200, r.text
    return r.json()["dev_code"]


def verified_signup(http, **changes):
    code = request_code(http)
    assert http.post("/auth/codes/verify", json={"email": EMAIL, "purpose": "SIGNUP", "code": code}).status_code == 200
    body = dict(email=EMAIL, password=PASSWORD, pin=PIN, name="김회원", agreed_term_ids=[1, 2])
    return http.post("/auth/signup", json=body | changes)


def login(http, **changes):
    return http.post("/auth/login", json=dict(email=EMAIL, password=PASSWORD) | changes)


def test_signup_login_profile_and_ledger(client):
    http, db = client
    assert verified_signup(http).status_code == 201
    user = db.scalar(select(User))
    assert user.password_hash != PASSWORD and verify_secret(user.password_hash, PASSWORD)
    assert user.pin != PIN and verify_secret(user.pin, PIN)
    account = db.scalar(select(Account))
    tx = db.scalar(select(AccountTransaction))
    assert account.user_id == user.id and account.balance == tx.amount == tx.new_balance == 1_000_000
    assert tx.memo == "가입 축하 가상머니"
    assert db.scalar(select(func.count()).select_from(TermAgreement)) == 3
    assert db.scalar(select(VerificationCode)).verified_at is None
    token = login(http).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert http.get("/me", headers=headers).json()["user_name"] == "김회원"
    assert http.patch("/me", headers=headers, json={"user_name": "새이름", "phone_num": "01012345678"}).status_code == 200
    assert user.user_name == "새이름"
    assert http.get("/auth/email-available", params={"email": EMAIL}).json() == {"available": False}
    assert len(http.get("/terms", params={"category": "SIGNUP"}).json()) == 3


def test_signup_requires_verification_and_terms(client):
    http, db = client
    body = dict(email=EMAIL, password=PASSWORD, pin=PIN, user_name="회원", agreed_term_ids=[1, 2])
    assert http.post("/auth/signup", json=body).json()["code"] == "CODE"
    assert verified_signup(http, agreed_term_ids=[1]).json()["code"] == "TERMS_REQUIRED"
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert db.scalar(select(func.count()).select_from(Account)) == 0


def test_duplicate_signup_does_not_credit_twice(client):
    http, db = client
    assert verified_signup(http).status_code == 201
    assert verified_signup(http).status_code == 409
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 1


def test_signup_rolls_back_if_initial_account_fails(client, monkeypatch):
    http, db = client
    def fail(_):
        raise RuntimeError("account creation failed")
    monkeypatch.setattr(auth, "new_account_num", fail)
    with pytest.raises(RuntimeError):
        verified_signup(http)
    assert db.scalar(select(func.count()).select_from(User)) == 0
    assert db.scalar(select(func.count()).select_from(TermAgreement)) == 0
    assert db.scalar(select(VerificationCode)).verified_at is not None


def test_latest_code_only_purpose_and_attempt_limit(client):
    http, db = client
    old = request_code(http)
    code = request_code(http)
    row = db.scalar(select(VerificationCode).order_by(VerificationCode.id.desc()))
    assert row.code_hash != code and verify_secret(row.code_hash, code)
    assert http.post("/auth/codes/verify", json={"email": EMAIL, "purpose": "RESET_PW", "code": code}).json()["code"] == "CODE"
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert http.post("/auth/codes/verify", json={"email": EMAIL, "purpose": "SIGNUP", "code": wrong}).status_code == 400
    assert row.attempts == 5
    assert http.post("/auth/codes/verify", json={"email": EMAIL, "purpose": "SIGNUP", "code": code}).status_code == 400
    # 정확한 최신 번호가 아니면 이전 번호를 다시 유효하게 만들 수 없다.
    row.code_hash = hash_secret("222222")
    row.attempts = 0
    db.commit()
    assert http.post("/auth/codes/verify", json={"email": EMAIL, "purpose": "SIGNUP", "code": old if old != "222222" else "333333"}).status_code == 400


def test_expired_code_and_verified_window(client):
    http, db = client
    code = request_code(http)
    row = db.scalar(select(VerificationCode))
    row.expires_at = now_kst() - timedelta(seconds=1)
    db.commit()
    assert http.post("/auth/codes/verify", json={"email": EMAIL, "purpose": "SIGNUP", "code": code}).status_code == 400
    row.verified_at = now_kst() - timedelta(minutes=11)
    db.commit()
    with pytest.raises(BankError):
        verification.assert_verified(db, EMAIL, "SIGNUP")


@pytest.mark.parametrize("use_pin", [False, True])
def test_login_lock_and_password_reset(client, use_pin):
    http, db = client
    assert verified_signup(http).status_code == 201
    token = login(http).json()["access_token"]
    path = "/auth/login/pin" if use_pin else "/auth/login"
    body = {"email": EMAIL, "pin": "000000"} if use_pin else {"email": EMAIL, "password": "wrong"}
    for i in range(5):
        assert http.post(path, json=body).status_code == (403 if i == 4 else 401)
    assert db.scalar(select(User)).status == "LOCKED"
    headers = {"Authorization": f"Bearer {token}"}
    assert http.get("/accounts", headers=headers).status_code == 401
    code = request_code(http, "RESET_PW")
    reset = {"email": EMAIL, "code": code, "new_password": "NewPassword123!"}
    assert http.post("/auth/password/reset", json=reset).status_code == 204
    assert http.post("/auth/password/reset", json=reset).status_code == 400
    assert login(http).status_code == 401
    assert login(http, password=reset["new_password"]).status_code == 200
    assert http.post("/auth/login/pin", json={"email": EMAIL, "pin": PIN}).status_code == 200
    assert db.scalar(select(User)).login_fail_count == 0


def test_login_history_and_new_device_notification(client):
    http, db = client
    verified_signup(http)
    assert login(http).status_code == 200
    assert login(http).status_code == 200
    assert db.scalar(select(func.count()).select_from(Notification)) == 0
    assert http.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}, headers={"User-Agent": "new-device"}).status_code == 200
    assert db.scalar(select(Notification)).type == "SUSPICIOUS_LOGIN"
    assert db.scalar(select(func.count()).select_from(LoginHistory)) == 3


def test_tokens_and_withdrawal(client):
    http, db = client
    verified_signup(http)
    user = db.scalar(select(User))
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    assert http.get("/me").status_code == 401
    expired = jwt.encode({"sub": str(user.id), "exp": now_kst() - timedelta(seconds=1)}, settings.jwt_secret, algorithm="HS256")
    assert http.get("/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    missing_exp = jwt.encode({"sub": str(user.id)}, settings.jwt_secret, algorithm="HS256")
    assert http.get("/me", headers={"Authorization": f"Bearer {missing_exp}"}).status_code == 401
    assert http.request("DELETE", "/me", headers=headers, json={"password": PASSWORD}).json()["code"] == "CLOSE_BLOCKED"
    db.scalar(select(Account)).status = "CLOSED"
    db.commit()
    assert http.request("DELETE", "/me", headers=headers, json={"password": "wrong"}).status_code == 401
    assert http.request("DELETE", "/me", headers=headers, json={"password": PASSWORD}).status_code == 204
    assert http.get("/accounts", headers=headers).status_code == 401
    assert login(http).status_code == 401
    assert db.scalar(select(AccountTransaction)) is not None


def test_account_pin_failures_suspend_only_that_account(client):
    http, db = client
    verified_signup(http)
    user, account = db.scalar(select(User)), db.scalar(select(Account))
    for _ in range(5):
        with pytest.raises(BankError):
            verify_pin(db, user, "000000", account)
    assert account.status == "SUSPENDED" and user.status == "ACTIVE"


def test_mail_failure_rolls_back_and_dev_code_is_explicit(client, monkeypatch):
    http, db = client
    monkeypatch.setattr(settings, "development", False)
    r = http.post("/auth/codes", json={"email": EMAIL, "purpose": "SIGNUP"})
    assert r.status_code == 400 and "dev_code" not in r.json()
    assert db.scalar(select(func.count()).select_from(VerificationCode)) == 0


def test_smtp_mode_does_not_return_code(client, monkeypatch):
    http, db = client
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    sent = []
    monkeypatch.setattr(verification, "send_mail", lambda *args: sent.append(args))
    r = http.post("/auth/codes", json={"email": EMAIL, "purpose": "SIGNUP"})
    assert r.status_code == 200 and "dev_code" not in r.json()
    assert len(sent) == 1 and sent[0][0] == EMAIL
    assert db.scalar(select(VerificationCode)) is not None


def test_invalid_input(client):
    http, _ = client
    r = verified_signup(http, pin="12345")
    assert r.status_code == 422 and "12345" not in r.text
    assert http.post("/auth/codes", json={"email": EMAIL, "purpose": "OTHER"}).status_code == 422
