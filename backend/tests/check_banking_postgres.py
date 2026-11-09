"""카드·자동이체 PostgreSQL 통합 검사. 임시 스키마만 사용하고 종료 시 제거한다."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api import auto_transfers as auto_api, cards as card_api, notifications as notification_api
from app.db import engine, get_db
from app.errors import BankError
from app.models import Account, AccountProduct, AccountTransaction, AutoTransfer, Base, Card, CardPayment, Notification, Transfer, User, now_kst
from app.security import create_access_token, hash_secret
from app.services import auto_transfers, cards


def main():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL에서 실행하세요.")
    schema = "banking_check_" + uuid.uuid4().hex
    isolated = engine.execution_options(schema_translate_map={None: schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        Base.metadata.create_all(isolated)
        secret = hash_secret("493827")
        with Session(isolated, expire_on_commit=False) as db:
            users = [User(email=f"u{i}@example.com", user_name=f"user{i}", password_hash=secret, pin=secret) for i in (1, 2)]
            product = AccountProduct(code="basic", product_name="test")
            db.add_all([*users, product])
            db.commit()
            owner, other = [u.id for u in users]
            product_id = product.id
        sequence = 0
        def pair(balance=500):
            nonlocal sequence
            sequence += 1
            with Session(isolated, expire_on_commit=False) as db:
                source = Account(user_id=owner, product_id=product_id, account_num=f"900-{sequence:04}-0001", account_password=secret, balance=balance)
                target = Account(user_id=other, product_id=product_id, account_num=f"901-{sequence:04}-0001", account_password=secret)
                db.add_all([source, target])
                db.commit()
                return source.id, target.id, target.account_num

        def parallel(fn):
            barrier = threading.Barrier(2)
            def work(_):
                barrier.wait(timeout=10)
                with Session(isolated, expire_on_commit=False) as db:
                    db.connection().exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                    try:
                        return fn(db)
                    except BankError as error:
                        return error.code
            with ThreadPoolExecutor(max_workers=2) as pool:
                return list(pool.map(work, (1, 2)))

        for balance, limit, expected in ((500, 1000, "INSUFFICIENT"), (2000, 500, "CARD_LIMIT")):
            source, target, _ = pair(balance)
            with Session(isolated) as db:
                issued = cards.issue(db, owner, source, limit, False)
            card_id = uuid.UUID(issued["id"]) if isinstance(issued["id"], str) else issued["id"]
            results = parallel(lambda db: (cards.pay(db, owner, card_id, 400, "test merchant", "test", False, uuid.uuid4().hex) and "ok"))
            assert sorted(results) == sorted(["ok", expected]), results
            with Session(isolated) as db:
                assert db.get(Account, source).balance == balance - 400
                assert db.scalar(select(func.count()).select_from(CardPayment).where(CardPayment.card_id == card_id)) == 1
                assert db.scalar(select(func.count()).select_from(AccountTransaction).where(AccountTransaction.account_id == source)) == 1
        print("PostgreSQL concurrent card checks passed: balance and card daily limit.")

        source, _, _ = pair(1000)
        with Session(isolated) as db:
            card_id = cards.issue(db, owner, source, 1000, False)["id"]
            before_notices = db.scalar(select(func.count()).select_from(Notification))
        results = parallel(lambda db: cards.pay(db, owner, card_id, 400, "same merchant", "test", False, "duplicate-payment"))
        assert results[0] == results[1], results
        with Session(isolated) as db:
            assert db.get(Account, source).balance == 600
            assert db.scalar(select(func.count()).select_from(CardPayment).where(CardPayment.card_id == card_id)) == 1
            assert db.scalar(select(func.count()).select_from(AccountTransaction).where(AccountTransaction.account_id == source)) == 1
            assert db.scalar(select(func.count()).select_from(Notification)) == before_notices + 1
        print("PostgreSQL duplicate card payment check passed: one charge, ledger row, and notification.")

        def job(balance=500):
            source, target, num = pair(balance)
            with Session(isolated, expire_on_commit=False) as db:
                row = AutoTransfer(from_account_id=source, to_account_id=target, amount=400, cycle="ONCE",
                    start_date=now_kst().date(), next_run_at=now_kst() - timedelta(seconds=1))
                db.add(row)
                db.commit()
                return row.id, source, target
        for balance, expected in ((500, "SUCCESS"), (0, "FAILED")):
            schedule_id, source, target = job(balance)
            with Session(isolated) as db:
                before = db.scalar(select(func.count()).select_from(Notification))
            at = now_kst()
            results = parallel(lambda db: auto_transfers.process_one(db, schedule_id, at))
            assert results.count(True) == 1 and results.count(False) == 1, results
            with Session(isolated) as db:
                rows = db.scalars(select(Transfer).where(Transfer.auto_transfer_id == schedule_id)).all()
                assert len(rows) == 1 and rows[0].status == expected
                assert db.get(AutoTransfer, schedule_id).status == "ENDED"
                assert db.get(Account, source).balance == (100 if balance else 0)
                count = db.scalar(select(func.count()).select_from(AccountTransaction).where(AccountTransaction.account_id == source))
                assert count == (1 if balance else 0)
                assert db.scalar(select(func.count()).select_from(Notification)) == before + (2 if balance else 1)
                if balance:
                    latest = db.scalars(select(Notification).order_by(Notification.id.desc()).limit(2)).all()
                    assert {(n.type, n.user_id) for n in latest} == {("TRANSFER_IN", other), ("AUTO_TRANSFER_SUCCESS", owner)}
                else:
                    assert db.scalar(select(Notification).order_by(Notification.id.desc())).type == "AUTO_TRANSFER_FAIL"

        schedule_id, source, target = job()
        original = auto_transfers.next_run
        def fail(*args, **kwargs):
            raise RuntimeError("simulated failure after money movement")
        auto_transfers.next_run = fail
        try:
            try:
                with Session(isolated) as db:
                    auto_transfers.process_one(db, schedule_id, now_kst())
            except RuntimeError:
                pass
        finally:
            auto_transfers.next_run = original
        with Session(isolated) as db:
            assert db.get(Account, source).balance == 500
            assert db.scalar(select(func.count()).select_from(Transfer).where(Transfer.auto_transfer_id == schedule_id)) == 0
            assert db.get(AutoTransfer, schedule_id).status == "ACTIVE"
        print("PostgreSQL schedule checks passed: success/failure once only, atomic rollback after execution.")

        source, target, number = pair(500)
        request_id = uuid.uuid4()
        run_at = now_kst() + timedelta(minutes=5)
        registrations = parallel(lambda db: auto_transfers.register(
            db, db.get(User, owner), idempotency_key=request_id, from_account_id=source, to_account_num=number,
            amount=100, pin="493827", cycle="ONCE", run_at=run_at, run_day=None, start_date=None,
            end_date=None, memo=None))
        assert all(isinstance(result, dict) and result["id"] == request_id for result in registrations), registrations
        with Session(isolated) as db:
            assert db.scalars(select(AutoTransfer.id).where(AutoTransfer.from_account_id == source)).all() == [request_id]
            assert auto_transfers.process_one(db, request_id, run_at)
            assert not auto_transfers.process_one(db, request_id, run_at)
            assert db.get(Account, source).balance == 400
            assert db.get(Account, target).balance == 100
            assert db.scalar(select(func.count()).select_from(Transfer).where(Transfer.auto_transfer_id == request_id)) == 1
        print("PostgreSQL concurrent registration replay passed: one schedule and one debit.")

        app = FastAPI()
        for router in (card_api.router, auto_api.router, notification_api.router):
            app.include_router(router)
        @app.exception_handler(BankError)
        def error(_, e):
            return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)
        def database():
            with Session(isolated, expire_on_commit=False) as db:
                yield db
        app.dependency_overrides[get_db] = database
        source, target, number = pair(5000)
        with TestClient(app, headers={"Authorization": "Bearer " + create_access_token(owner)}) as http:
            response = http.post("/cards", json={"account_id": str(source)})
            assert response.status_code == 201, response.text
            card_id = response.json()["id"]
            assert "card_number" not in response.json() and len(response.json()["last4"]) == 4
            assert http.post(f"/cards/{card_id}/payments", json={"amount": 100, "place": "test merchant", "idempotency_key": "api-card-payment"}).status_code == 201
            assert http.post(f"/cards/{card_id}/lost", json={"pin": "493827"}).json()["status"] == "LOST"
            replacement = http.post(f"/cards/{card_id}/reissue", json={"pin": "493827"})
            assert replacement.status_code == 201
            new_card_path = f"/cards/{replacement.json()['id']}"
            assert http.patch(new_card_path, json={"pin": "493827", "daily_limit": 100}).status_code == 200
            blocked = http.post(new_card_path + "/payments", json={"amount": 1, "place": "test merchant",
                                                                  "idempotency_key": "reissue-limit-check"})
            assert blocked.json()["code"] == "CARD_LIMIT"
            request = {"from_account_id": str(source), "to_account_num": number, "amount": 100, "idempotency_key": str(uuid.uuid4()),
                "pin": "493827", "cycle": "ONCE", "run_at": (now_kst() + timedelta(minutes=5)).isoformat()}
            response = http.post("/auto-transfers", json=request)
            assert response.status_code == 201, response.text
            assert http.get("/auto-transfers").status_code == 200
            assert http.delete("/auto-transfers/" + response.json()["id"]).status_code == 204
            assert http.get("/notifications").json()["unread"] > 0
            assert http.post("/notifications/read-all").status_code == 204
            assert http.get("/notifications").json()["unread"] == 0
        print("PostgreSQL API checks passed: encrypted cards, payment, lost/reissue, scheduling/cancel, notification read.")
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        print("Temporary test schema removed. Existing application data was untouched.")


if __name__ == "__main__":
    main()
