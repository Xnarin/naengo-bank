import uuid
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.transfers import router
from app.db import get_db
from app.errors import BankError
from app.models import Account, AccountProduct, AccountTransaction, Base, FavoriteRecipient, Transfer, User, now_kst
from app.security import create_access_token, hash_secret
from app.services.transfers import transfer

PIN = "493827"


@pytest.fixture
def bank():
    # 작업 중인 에이전트를 읽지 않고 실제 은행 라우터만 검증한다.
    app = FastAPI()
    app.include_router(router)
    @app.exception_handler(BankError)
    def error(_, e):
        return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        secret = hash_secret(PIN)
        user = User(email="sender@example.com", user_name="김송금", password_hash=secret, pin=secret)
        other = User(email="receiver@example.com", user_name="홍길동", password_hash=secret, pin=secret)
        product = AccountProduct(code="basic", product_name="기본통장")
        db.add_all([user, other, product])
        db.flush()
        source = Account(user_id=user.id, product_id=product.id, account_num="111-1111-1111", account_password=secret, balance=2_000_000)
        mine = Account(user_id=user.id, product_id=product.id, account_num="222-2222-2222", account_password=secret, nickname="생활비")
        target = Account(user_id=other.id, product_id=product.id, account_num="333-3333-3333", account_password=secret)
        db.add_all([source, mine, target])
        db.commit()
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app, headers={"Authorization": "Bearer " + create_access_token(user.id)}) as http:
            yield http, db, user, other, source, mine, target
    engine.dispose()


def body(source, target, **changes):
    return {"from_account_id": str(source.id), "to_account_num": target.account_num,
            "amount": 10_000, "memo": "용돈", "pin": PIN, "idempotency_key": uuid.uuid4().hex} | changes


def test_recipient_masking_and_status(bank):
    http, db, _, _, source, mine, target = bank
    response = http.get("/transfers/recipient", params={"account_num": target.account_num})
    assert response.json() == {"account_num": target.account_num, "holder_name": "홍*동", "mine": False}
    assert http.get("/transfers/recipient", params={"account_num": mine.account_num}).json()["holder_name"] == "생활비"
    target.status = "SUSPENDED"
    db.commit()
    assert http.get("/transfers/recipient", params={"account_num": target.account_num}).status_code == 400
    assert http.get("/transfers/recipient", params={"account_num": "999-9999-9999"}).status_code == 404


def test_results_replays_are_historical_and_owned(bank):
    http, db, _, other, source, mine, target = bank
    request = body(source, target)
    first = http.post("/transfers", json=request)
    assert first.status_code == 201 and first.json()["new_balance"] == 1_990_000
    assert first.json()["to_name"] == "홍*동"
    assert http.post("/transfers", json=body(source, target)).status_code == 201
    assert http.post("/transfers", json=request).json() == first.json()
    assert http.get("/transfers/by-key/" + request["idempotency_key"]).json() == first.json()
    assert db.scalar(select(func.count()).select_from(Transfer)) == 2
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 4
    http.headers["Authorization"] = "Bearer " + create_access_token(other.id)
    assert http.get("/transfers/by-key/" + request["idempotency_key"]).status_code == 404
    assert http.get("/transfers/by-key/unknown-key").status_code == 404


@pytest.mark.parametrize("changes", [{"amount": 20000}, {"memo": "다른 요청"}, {"to_account_num": "222-2222-2222"}])
def test_same_key_different_payload_is_conflict(bank, changes):
    http, db, _, _, source, _, target = bank
    request = body(source, target)
    assert http.post("/transfers", json=request).status_code == 201
    assert http.post("/transfers", json=request | changes).status_code == 409
    assert db.get(Account, source.id).balance == 1_990_000
    assert db.scalar(select(func.count()).select_from(Transfer)) == 1


@pytest.mark.parametrize("amount", [1.0, 1.5, True, "1000", 0, -1])
def test_amount_requires_positive_integer(bank, amount):
    http, db, _, _, source, _, target = bank
    assert http.post("/transfers", json=body(source, target, amount=amount)).status_code == 422
    assert db.get(Account, source.id).balance == 2_000_000
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 0


def test_keys_fit_database_column(bank):
    http, _, _, _, source, _, target = bank
    assert http.post("/transfers", json=body(source, target, idempotency_key="x" * 58)).status_code == 201
    assert http.post("/transfers", json=body(source, target, idempotency_key="x" * 59)).status_code == 422


def test_recent_is_distinct_and_owned(bank):
    http, db, user, other, source, mine, target = bank
    one = transfer(db, source.id, target.id, 10_000, "first")
    one.complete_at = now_kst() - timedelta(days=2)
    transfer(db, source.id, mine.id, 10_000, "second")
    transfer(db, source.id, target.id, 10_000, "third")
    result = http.get("/transfers/recent").json()
    assert len(result) == 2 and result[0]["account_num"] == target.account_num
    assert result[0]["holder_name"] == "홍*동" and result[1]["holder_name"] == "생활비"
    http.headers["Authorization"] = "Bearer " + create_access_token(other.id)
    assert http.get("/transfers/recent").json() == []


def test_favorites_upsert_alias_and_owner_checks(bank):
    http, db, _, other, source, mine, target = bank
    first = http.post("/favorite-recipients", json={"account_num": target.account_num, "alias": "친구"})
    assert first.status_code == 201 and first.json()["holder_name"] == "홍*동"
    item_id = first.json()["id"]
    # 예금주 이름은 클라이언트 입력이 아니라 계좌 소유자에게서 가져온다.
    assert db.get(FavoriteRecipient, item_id).holder_name == "홍길동"
    second = http.post("/favorite-recipients", json={"account_num": target.account_num, "alias": "길동이"})
    assert second.json()["id"] == item_id and second.json()["alias"] == "길동이"
    assert len(http.get("/favorite-recipients").json()) == 1
    assert http.patch(f"/favorite-recipients/{item_id}", json={"alias": "엄마"}).json()["alias"] == "엄마"
    token = http.headers["Authorization"]
    http.headers["Authorization"] = "Bearer " + create_access_token(other.id)
    assert http.get("/favorite-recipients").json() == []
    assert http.patch(f"/favorite-recipients/{item_id}", json={"alias": "침입"}).status_code == 404
    assert http.delete(f"/favorite-recipients/{item_id}").status_code == 404
    http.headers["Authorization"] = token
    assert http.delete(f"/favorite-recipients/{item_id}").status_code == 204
    assert http.get("/favorite-recipients").json() == []


def test_insufficient_limit_and_invalid_owner_do_not_write(bank):
    http, db, _, _, source, mine, target = bank
    assert http.post("/transfers", json=body(target, source)).status_code == 404
    assert http.post("/transfers", json=body(mine, target)).json()["code"] == "INSUFFICIENT"
    assert http.post("/transfers", json=body(source, target, amount=1_000_001)).json()["code"] == "LIMIT"
    assert db.scalar(select(func.count()).select_from(Transfer)) == 0
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 0


def test_long_term_limit_and_own_account_exemption(bank):
    http, db, _, _, source, mine, target = bank
    source.daily_limit = 1_000_000
    source.month_limit = 100_000
    db.commit()
    assert http.post("/transfers", json=body(source, target, amount=80_000)).status_code == 201
    assert http.post("/transfers", json=body(source, target, amount=30_000)).json()["code"] == "LIMIT"
    assert http.post("/transfers", json=body(source, mine, amount=1_200_000)).status_code == 201


def test_pin_is_required_even_for_retries(bank):
    http, db, _, _, source, _, target = bank
    request = body(source, target)
    assert http.post("/transfers", json=request).status_code == 201
    assert http.post("/transfers", json=request | {"pin": "000000"}).status_code == 401
    assert db.scalar(select(func.count()).select_from(Transfer)) == 1
    http.headers.pop("Authorization")
    assert http.get("/transfers/recent").status_code == 401
    assert http.get("/favorite-recipients").status_code == 401
