"""실제 PostgreSQL 동시 송금 검사. 임시 스키마만 생성하고 검사 후 제거한다.

컨테이너에서 실행: python /checks/check_transfer_postgres.py
기존 public 스키마의 회원·계좌·거래는 읽거나 수정하지 않는다.
"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.api.transfers import router
from app.db import engine, get_db
from app.errors import BankError
from app.models import Account, AccountProduct, AccountTransaction, Base, Transfer, User
from app.services.transfers import transfer
from app.security import create_access_token, hash_secret


def main():
    if engine.dialect.name != "postgresql":
        raise RuntimeError("이 검사는 PostgreSQL에서만 실행하세요.")
    schema = "transfer_check_" + uuid.uuid4().hex
    test_engine = engine.execution_options(schema_translate_map={None: schema})
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        Base.metadata.create_all(test_engine)
        secret = hash_secret("493827")
        with Session(test_engine, expire_on_commit=False) as db:
            product = AccountProduct(code="test", product_name="test")
            users = [User(email=f"user{i}@example.com", user_name=f"test{i}", password_hash=secret, pin=secret) for i in range(2)]
            db.add_all([product, *users])
            db.commit()
            ids = [u.id for u in users]
            product_id = product.id
        sequence = 0

        def pair():
            nonlocal sequence
            sequence += 1
            with Session(test_engine, expire_on_commit=False) as db:
                rows = [Account(user_id=uid, product_id=product_id, account_num=f"{900 + i}-{sequence:04}-0001",
                                account_password="unused", balance=500) for i, uid in enumerate(ids)]
                db.add_all(rows)
                db.commit()
                return tuple(a.id for a in rows)

        def parallel(jobs):
            barrier = threading.Barrier(2)
            local = threading.local()
            def synchronize(_, __, statement, *args):
                # 두 요청의 첫 중복 조회를 모두 마친 다음 계좌 잠금을 경쟁시킨다.
                if (threading.current_thread().name.startswith("transfer-race")
                        and statement.lstrip().upper().startswith("SELECT") and ".transfers" in statement
                        and not getattr(local, "synced", False)):
                    local.synced = True
                    barrier.wait(timeout=10)
            def execute(job):
                with Session(test_engine, expire_on_commit=False) as db:
                    db.connection().exec_driver_sql("SET LOCAL lock_timeout = '8s'")
                    try:
                        return "ok", transfer(db, *job).id
                    except BankError as error:
                        return "error", error.code
            event.listen(test_engine, "after_cursor_execute", synchronize)
            try:
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="transfer-race") as pool:
                    return list(pool.map(execute, jobs))
            finally:
                event.remove(test_engine, "after_cursor_execute", synchronize)

        def snapshot(source, target):
            with Session(test_engine) as db:
                return (db.get(Account, source).balance, db.get(Account, target).balance,
                        db.scalar(select(func.count()).select_from(Transfer).where(Transfer.from_account_id == source)),
                        db.scalar(select(func.count()).select_from(AccountTransaction).where(AccountTransaction.account_id == source)))

        source, target = pair()
        results = parallel([(source, target, 400, "same-key"), (source, target, 400, "same-key")])
        assert results[0] == results[1] and results[0][0] == "ok", results
        assert snapshot(source, target) == (100, 900, 1, 1)

        source, target = pair()
        results = parallel([(source, target, 400, "spend-a"), (source, target, 400, "spend-b")])
        assert sorted(r[0] for r in results) == ["error", "ok"] and ("error", "INSUFFICIENT") in results, results
        assert snapshot(source, target) == (100, 900, 1, 1)

        source, target = pair()
        results = parallel([(source, target, 400, "forward"), (target, source, 400, "reverse")])
        assert all(r[0] == "ok" for r in results), results
        assert snapshot(source, target) == (500, 500, 1, 2)

        source, target = pair()
        source2, target2 = pair()
        results = parallel([(source, target, 400, "conflicting-key"), (source2, target2, 400, "conflicting-key")])
        assert sorted(r[0] for r in results) == ["error", "ok"] and ("error", "INVALID_AMOUNT") in results, results
        states = [snapshot(source, target), snapshot(source2, target2)]
        assert sorted(states) == [(100, 900, 1, 1), (500, 500, 0, 0)], states
        print("PostgreSQL concurrent checks passed: duplicate submission, competing withdrawals, reverse transfers, conflicting keys across account pairs.")

        app = FastAPI()
        app.include_router(router)
        @app.exception_handler(BankError)
        def error(_, e):
            return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)
        def database():
            with Session(test_engine, expire_on_commit=False) as db:
                yield db
        app.dependency_overrides[get_db] = database
        source, target = pair()
        with Session(test_engine) as db:
            target_num = db.get(Account, target).account_num
        with TestClient(app, headers={"Authorization": "Bearer " + create_access_token(ids[0])}) as http:
            request = {"from_account_id": str(source), "to_account_num": target_num,
                       "amount": 100, "pin": "493827", "idempotency_key": "api-pg-check"}
            first = http.post("/transfers", json=request)
            assert first.status_code == 201, first.text
            assert http.post("/transfers", json=request).json() == first.json()
            assert http.get("/transfers/by-key/api-pg-check").json() == first.json()
            assert http.get("/transfers/recent").status_code == 200
            favorite = http.post("/favorite-recipients", json={"account_num": target_num, "alias": "friend"})
            assert favorite.status_code == 201, favorite.text
            item_id = favorite.json()["id"]
            assert http.patch(f"/favorite-recipients/{item_id}", json={"alias": "new alias"}).status_code == 200
            assert len(http.get("/favorite-recipients").json()) == 1
            assert http.delete(f"/favorite-recipients/{item_id}").status_code == 204
        print("PostgreSQL API checks passed: PIN transfer, replay, result lookup, recent recipients, favorite CRUD.")
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        print("Temporary test schema removed; existing application data was untouched.")


if __name__ == "__main__":
    main()
