import ast
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent import evaluate, graph as agent
from app.api import agent as api
from app.db import get_db
from app.main import app
from app.models import Account, AccountTransaction, Card, Transfer, User
from app.security import create_access_token


@pytest.fixture
def bank(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'orchestration.db'}")
    with evaluate.seed(engine=engine):
        pass

    def get_test_db():
        with Session(engine) as db:
            yield db

    def restart():
        compiled = agent.b.compile(checkpointer=InMemorySaver())
        monkeypatch.setattr(agent, "graph", compiled)
        monkeypatch.setattr(api, "graph", compiled)
        monkeypatch.setattr(api, "THREAD_OWNER", {})

    restart()
    monkeypatch.setitem(app.dependency_overrides, get_db, get_test_db)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, engine, restart
    engine.dispose()


def auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def chat(client, message, *, user=evaluate.ME, thread_id=None):
    return client.post("/agent/chat", headers=auth(user), json={"message": message, "thread_id": thread_id})


def confirm(client, action, *, user=evaluate.ME, approved=True, pin=evaluate.PIN):
    return client.post("/agent/confirm", headers=auth(user),
                       json={**action, "approved": approved, "pin": pin})


def prepare_transfers(monkeypatch):
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="TRANSFER")))
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=lambda prompt: agent.TransferSlots(
        recipient="엄마", amount=20_000 if prompt.endswith("엄마에게 2만원 보내줘") else 10_000)))


def pending_transfer(client, amount, thread_id=None):
    response = chat(client, f"엄마에게 {amount // 10_000}만원 보내줘", thread_id=thread_id)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "confirm"
    assert data["confirm"]["금액"] == amount
    return {"thread_id": data["thread_id"], "confirmation_id": data["confirmation_id"]}


def assert_ledger(engine, amount=0):
    with Session(engine) as db:
        assert db.get(Account, evaluate.A_MAIN).balance == 1_284_500 - amount
        assert db.get(Account, evaluate.A_MOM).balance == 300_000 + amount
        assert db.scalars(select(Transfer.amount)).all() == ([amount] if amount else [])
        entries = db.execute(select(AccountTransaction.account_id, AccountTransaction.transaction_direction,
                                    AccountTransaction.amount).where(AccountTransaction.transfer_id.is_not(None))).all()
        assert set(entries) == ({(evaluate.A_MAIN, "OUT", amount), (evaluate.A_MOM, "IN", amount)} if amount else set())
        assert len(entries) == (2 if amount else 0)


def test_overlapping_balance_requests_use_each_users_real_tool_data(bank, monkeypatch):
    client, _, _ = bank
    overlap = Barrier(2, timeout=10)
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="ACCOUNT_QUERY")))

    def invoke(messages):
        if isinstance(messages[-1], ToolMessage):
            balances = [row["잔액"] for row in ast.literal_eval(messages[-1].content)]
            return AIMessage(content=" / ".join(f"{balance:,}원" for balance in balances))
        overlap.wait()
        return AIMessage(content="", tool_calls=[{"name": "list_accounts", "args": {}, "id": "balance"}])

    monkeypatch.setattr(agent, "llm", SimpleNamespace(bind_tools=lambda _: SimpleNamespace(invoke=invoke)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = [future.result() for future in (
            pool.submit(chat, client, "내 잔액 알려줘"),
            pool.submit(chat, client, "내 잔액 알려줘", user=evaluate.MOM),
        )]
    assert a.status_code == b.status_code == 200
    own, other = a.json(), b.json()
    assert own["thread_id"] != other["thread_id"]
    assert own["status"] == other["status"] == "answered"
    a_text, b_text = (data["blocks"][0]["text"] for data in (own, other))
    assert all(amount in a_text and amount not in b_text for amount in ("1,284,500원", "5,020,000원", "412,300원"))
    assert b_text == "300,000원" and "300,000원" not in a_text


def test_cross_user_thread_access_and_cancel_leave_no_transfer(bank, monkeypatch):
    client, engine, _ = bank
    prepare_transfers(monkeypatch)
    action = pending_transfer(client, 10_000)
    assert chat(client, "이어서 보여줘", user=evaluate.MOM, thread_id=action["thread_id"]).status_code == 404
    assert confirm(client, action, user=evaluate.MOM).status_code == 404
    assert_ledger(engine)
    assert confirm(client, action, approved=False).json()["status"] == "cancelled"
    assert confirm(client, action).status_code == 409
    assert_ledger(engine)


def test_restart_invalidates_unapproved_transfer(bank, monkeypatch):
    client, engine, restart = bank
    prepare_transfers(monkeypatch)
    old_action = pending_transfer(client, 10_000)
    restart()
    assert confirm(client, old_action).status_code == 404
    assert chat(client, "이어서 보여줘", thread_id=old_action["thread_id"]).status_code == 404
    assert pending_transfer(client, 10_000)["thread_id"] != old_action["thread_id"]
    assert_ledger(engine)


def test_two_overlapping_approvals_write_one_transfer(bank, monkeypatch):
    client, engine, _ = bank
    prepare_transfers(monkeypatch)
    action = pending_transfer(client, 10_000)
    pin_verified = Event()
    release = Event()
    resume = api.resume

    def pause_after_pin(*args, **kwargs):
        pin_verified.set()
        assert release.wait(10)
        return resume(*args, **kwargs)

    monkeypatch.setattr(api, "resume", pause_after_pin)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(confirm, client, action)
        try:
            assert pin_verified.wait(10)
            for request in (pool.submit(confirm, client, action),
                            pool.submit(chat, client, "엄마에게 2만원 보내줘", thread_id=action["thread_id"])):
                response = request.result(timeout=5)
                assert response.status_code == 409
                assert response.json()["code"] == "THREAD_BUSY"
        finally:
            release.set()
        response = first.result(timeout=10)
    assert response.status_code == 200 and response.json()["status"] == "done"
    assert confirm(client, action).status_code == 409
    assert_ledger(engine, 10_000)


def test_stale_approval_cannot_execute_replacement_transfer(bank, monkeypatch):
    client, engine, _ = bank
    prepare_transfers(monkeypatch)
    old = pending_transfer(client, 10_000)
    new = pending_transfer(client, 20_000, old["thread_id"])
    assert new["thread_id"] == old["thread_id"]
    assert new["confirmation_id"] != old["confirmation_id"]

    assert confirm(client, {"thread_id": old["thread_id"]}).status_code == 422
    for approved in (True, False):
        response = confirm(client, old, approved=approved, pin="000000")
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "STALE_CONFIRMATION"
    with Session(engine) as db:
        assert db.get(User, evaluate.ME).pin_fail_count == 0
    assert_ledger(engine)

    response = confirm(client, new)
    assert response.status_code == 200 and response.json()["status"] == "done"
    assert confirm(client, new).status_code == 409
    assert_ledger(engine, 20_000)


@pytest.mark.parametrize("message", ["카드 정지해줘", "끝자리 4821 카드 정지해줘"])
def test_card_confirmation_still_executes_with_matching_id(bank, monkeypatch, message):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="CARD_ACTION")))
    monkeypatch.setattr(agent, "card_llm", SimpleNamespace(invoke=lambda _: agent.CardSlots(action="SUSPEND")))
    response = chat(client, message)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "confirm"
    action = {"thread_id": data["thread_id"], "confirmation_id": data["confirmation_id"]}
    assert confirm(client, action).json()["status"] == "done"
    with Session(engine) as db:
        assert db.get(Card, evaluate.CARD).status == "SUSPENDED"


@pytest.mark.parametrize("model_hint", ["9999", "4821", None])
def test_unknown_card_never_confirms_another_card(bank, monkeypatch, model_hint):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="CARD_ACTION")))
    monkeypatch.setattr(agent, "card_llm", SimpleNamespace(
        invoke=lambda _: agent.CardSlots(action="SUSPEND", card_hint=model_hint)))

    response = chat(client, "끝자리 9999 카드 정지해줘")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ask"
    assert data["confirm"] is None and data["confirmation_id"] is None
    with Session(engine) as db:
        assert db.get(Card, evaluate.CARD).status == "ACTIVE"


@pytest.mark.parametrize("number", ["220-1111-2222", "22011112222", "220 1111 2222"])
def test_account_number_stays_out_of_models_but_transfer_uses_exact_account(bank, monkeypatch, number):
    client, engine, _ = bank
    router_prompts, slot_prompts = [], []

    def route(prompt):
        router_prompts.append(prompt)
        return agent.Route(intent="TRANSFER")

    def slots(prompt):
        slot_prompts.append(prompt)
        if len(slot_prompts) == 1:
            assert prompt.endswith("[계좌번호1]로 보내줘")
            return agent.TransferSlots(recipient="[계좌번호1]")
        return agent.TransferSlots(amount=10_000)

    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=route))
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=slots))
    first = chat(client, f"{number}로 보내줘").json()
    assert first["status"] == "ask"
    second = chat(client, "1만원 보내줘", thread_id=first["thread_id"]).json()
    assert second["status"] == "confirm"
    assert second["confirm"]["금액"] == 10_000
    assert len(router_prompts) == len(slot_prompts) == 2
    assert "220-****-2222로 보내줘" in router_prompts[1]
    for prompt in router_prompts + slot_prompts:
        assert all(raw not in prompt for raw in ("220-1111-2222", "22011112222", "220 1111 2222"))
    assert confirm(client, {"thread_id": second["thread_id"], "confirmation_id": second["confirmation_id"]}).json()["status"] == "done"
    assert_ledger(engine, 10_000)


def test_transfer_result_survives_restart_and_is_visible_only_to_sender(bank, monkeypatch):
    client, engine, restart = bank
    prepare_transfers(monkeypatch)
    action = pending_transfer(client, 10_000)
    path = "/agent/transfers/" + action["confirmation_id"]
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth(evaluate.ME)).json() == {"status": "UNKNOWN"}

    assert confirm(client, action).json()["status"] == "done"
    restart()

    result = client.get(path, headers=auth(evaluate.ME))
    assert result.json() == {"status": "SUCCESS", "amount": 10_000}
    assert result.headers["cache-control"] == "no-store"
    assert client.get(path, headers=auth(evaluate.MOM)).json() == {"status": "UNKNOWN"}
    assert_ledger(engine, 10_000)
