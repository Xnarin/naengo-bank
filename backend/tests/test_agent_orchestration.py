import ast
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from decimal import Decimal
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
from app.models import Account, AccountProduct, AccountTransaction, AutoTransfer, Card, Transfer, User, now_kst
from app.security import create_access_token
from app.services.recommendations import product_catalog


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


@pytest.mark.parametrize(("message", "intent", "path"), [
    ("계좌 만들어줘", "OPEN_ACCOUNT", "/products"),
    ("카드 만들어줘", "ISSUE_CARD", "/cards/new"),
    ("자동이체 내역 보여줘", "AUTO_TRANSFER_LIST", "/auto-transfers"),
])
def test_agent_links_to_existing_screen(bank, monkeypatch, message, intent, path):
    client, _, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent=intent)))
    data = chat(client, message).json()
    assert data["status"] == "guided" and data["confirmation_id"] is None
    assert next(b["links"][0]["to"] for b in data["blocks"] if b["kind"] == "links") == path


@pytest.mark.parametrize(("frequency", "cycle", "day", "label"), [
    ("매주 금요일", "WEEKLY", 4, "매주 금요일"),
    ("매월 15일", "MONTHLY", 15, "매월 15일"),
])
def test_chat_auto_transfer_registers_once_after_pin_without_immediate_debit(bank, monkeypatch, frequency, cycle, day, label):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="AUTO_TRANSFER")))
    monkeypatch.setattr(agent, "auto_slot_llm", SimpleNamespace(
        invoke=lambda _: agent.AutoTransferSlots(recipient="엄마", amount=10_000, cycle=cycle)))

    data = chat(client, f"{frequency} 엄마한테 1만원 자동이체해줘").json()
    assert data["status"] == "confirm" and data["confirmation_type"] == "AUTO_TRANSFER"
    assert data["confirm"]["주기"] == label
    assert data["confirm"]["첫 이체 예정"].endswith("09:00 (한국 시간)")
    action = {"thread_id": data["thread_id"], "confirmation_id": data["confirmation_id"]}
    assert confirm(client, action, pin="000000").status_code >= 400
    assert confirm(client, action, user=evaluate.MOM).status_code == 404
    with Session(engine) as db:
        assert db.scalars(select(AutoTransfer)).all() == []
    assert confirm(client, action).json()["status"] == "done"
    assert confirm(client, action).status_code == 409
    schedules = client.get("/auto-transfers", headers=auth(evaluate.ME)).json()
    assert [item["id"] for item in schedules] == [data["confirmation_id"]]
    assert client.get("/auto-transfers", headers=auth(evaluate.MOM)).json() == []
    with Session(engine) as db:
        schedule, = db.scalars(select(AutoTransfer)).all()
        assert str(schedule.id) == data["confirmation_id"]
        assert (schedule.from_account_id, schedule.to_account_id, schedule.amount) == (evaluate.A_MAIN, evaluate.A_MOM, 10_000)
        assert (schedule.cycle, schedule.run_day) == (cycle, day)
    assert_ledger(engine)


def test_auto_transfer_stepwise_amount_remains_schedule_through_pin(bank, monkeypatch):
    client, engine, _ = bank
    with Session(engine) as db:
        db.get(Account, evaluate.A_MAIN).is_favorite = False
        db.commit()
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="AUTO_TRANSFER")))
    monkeypatch.setattr(agent, "auto_slot_llm", SimpleNamespace(invoke=lambda _: agent.AutoTransferSlots()))
    data = chat(client, "자동 송금 예약").json()
    thread = data["thread_id"]
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="TRANSFER")))
    for message in ("220-1111-2222", "110-4823-0591에서", "500원", "매월"):
        data = chat(client, message, thread_id=thread).json()
        assert data["status"] == "ask" and data["confirm"] is None
    data = chat(client, "15일", thread_id=thread).json()
    assert data["confirmation_type"] == "AUTO_TRANSFER"
    assert data["confirm"]["금액"] == 500 and data["confirm"]["주기"] == "매월 15일"
    assert_ledger(engine)
    assert confirm(client, {"thread_id": thread, "confirmation_id": data["confirmation_id"]}).json()["status"] == "done"
    with Session(engine) as db:
        schedule, = db.scalars(select(AutoTransfer)).all()
        assert (schedule.from_account_id, schedule.to_account_id, schedule.amount) == (evaluate.A_MAIN, evaluate.A_MOM, 500)
        assert schedule.cycle == "MONTHLY" and schedule.run_day == 15
    assert_ledger(engine)


def test_schedule_asks_for_missing_day_and_unsupported_time_can_be_corrected(bank, monkeypatch):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="AUTO_TRANSFER")))
    monkeypatch.setattr(agent, "auto_slot_llm", SimpleNamespace(invoke=lambda prompt: agent.AutoTransferSlots(
        recipient="엄마", amount=10_000, cycle="MONTHLY") if "메시지: 매월" in prompt else agent.AutoTransferSlots()))

    first = chat(client, "매월 엄마한테 1만원 자동이체해줘").json()
    assert first["status"] == "ask" and first["confirm"] is None
    second = chat(client, "오후 3시로", thread_id=first["thread_id"]).json()
    assert second["status"] == "ask" and "오전 9시" in second["blocks"][0]["text"]
    third = chat(client, "오전 9시로 등록해줘", thread_id=first["thread_id"]).json()
    assert third["status"] == "ask" and "며칠" in third["blocks"][0]["text"]
    fourth = chat(client, "15일에", thread_id=first["thread_id"]).json()
    assert fourth["status"] == "confirm" and fourth["confirm"]["주기"] == "매월 15일"
    action = {"thread_id": fourth["thread_id"], "confirmation_id": fourth["confirmation_id"]}
    assert confirm(client, action, approved=False).json()["status"] == "cancelled"
    with Session(engine) as db:
        assert db.scalars(select(AutoTransfer)).all() == []


def test_schedule_requires_new_confirmation_if_first_run_has_passed(bank, monkeypatch):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="AUTO_TRANSFER")))
    monkeypatch.setattr(agent, "auto_slot_llm", SimpleNamespace(
        invoke=lambda _: agent.AutoTransferSlots(recipient="엄마", amount=10_000, cycle="WEEKLY")))
    data = chat(client, "매주 금요일에 엄마한테 1만원 자동이체해줘").json()
    first_run = datetime.fromisoformat(data["confirm"]["첫 이체 예정"].split(" (")[0]).replace(tzinfo=now_kst().tzinfo)
    monkeypatch.setattr(agent.auto_transfers, "now_kst", lambda: first_run + timedelta(seconds=1))

    action = {"thread_id": data["thread_id"], "confirmation_id": data["confirmation_id"]}
    result = confirm(client, action).json()
    assert result["status"] == "failed" and "예정일이 바뀌었어요" in result["blocks"][0]["text"]
    with Session(engine) as db:
        assert db.scalars(select(AutoTransfer)).all() == []
    assert_ledger(engine)


@pytest.mark.parametrize(("schedule", "cycle", "message"), [
    ("매주 금요일 또는 월요일", "WEEKLY", "무슨 요일"),
    ("매월 15일 또는 20일", "MONTHLY", "며칠"),
    ("매주 금요일 자정", "WEEKLY", "오전 9시"),
    ("매월 15일 오후 세 시", "MONTHLY", "오전 9시"),
    ("매월 12월 1일부터", "MONTHLY", "며칠"),
])
def test_schedule_does_not_choose_an_ambiguous_day_or_ignore_a_time(bank, monkeypatch, schedule, cycle, message):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="AUTO_TRANSFER")))
    monkeypatch.setattr(agent, "auto_slot_llm", SimpleNamespace(
        invoke=lambda _: agent.AutoTransferSlots(recipient="엄마", amount=10_000, cycle=cycle)))
    data = chat(client, f"{schedule} 엄마한테 1만원 자동이체해줘").json()
    assert data["status"] == "ask" and data["confirmation_id"] is None
    assert message in data["blocks"][0]["text"]
    with Session(engine) as db:
        assert db.scalars(select(AutoTransfer)).all() == []


def test_monthly_sent_total_matches_account_and_outgoing_rows(bank, monkeypatch):
    client, engine, _ = bank
    now = now_kst()
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(
        invoke=lambda _: agent.Route(intent="SENT_TOTAL", sent_to="엄마")))
    with Session(engine) as db:
        for source, direction, amount, number, at in [
            (evaluate.A_MAIN, "OUT", 17_000, "220-1111-2222", now),
            (evaluate.A_PARK, "OUT", 50_000, "220-1111-2222", now),
            (evaluate.A_MAIN, "IN", 91_000, "220-1111-2222", now),
            (evaluate.A_MAIN, "OUT", 42_000, "220-1111-2222", now.replace(day=1) - timedelta(days=1)),
            (evaluate.A_MAIN, "OUT", 99_000, "220-3333-4444", now),
            (evaluate.A_MOM, "OUT", 88_000, "220-1111-2222", now),
        ]:
            db.add(AccountTransaction(account_id=source, transaction_type="TRANSFER", transaction_direction=direction,
                                      amount=amount, counterparty_account=number, counterparty_name="김순자",
                                      memo="엄마", new_balance=0, transaction_at=at))
        # Use the explicit alias to distinguish it from an intentionally ambiguous historical name.
        db.commit()
    response = chat(client, "이번 달 엄마한테 얼마 보냈지?")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered" and data["confirm"] is None
    assert "2건, 총 67,000원" in data["blocks"][0]["text"]


def test_same_name_monthly_total_asks_for_account(bank, monkeypatch):
    client, _, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda prompt: agent.Route(
        intent="SENT_TOTAL", sent_to="[계좌번호1]" if "메시지: 이번 달에 [계좌번호1]" in prompt else "이서준")))
    first = chat(client, "이번 달 이서준에게 얼마 보냈지?").json()
    assert first["status"] == "ask"
    choices = next(b["options"] for b in first["blocks"] if b["kind"] == "choices")
    assert len(choices) == 2
    assert chat(client, choices[0]["value"], thread_id=first["thread_id"]).json()["status"] == "answered"


def test_repeat_amount_uses_latest_for_exact_recipient_and_still_needs_pin(bank, monkeypatch):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="TRANSFER")))
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=lambda _: agent.TransferSlots(recipient="엄마", amount=99_000)))
    now = now_kst()
    with Session(engine) as db:
        for amount, number, day in [(20_000, "220-1111-2222", 2), (10_000, "220-1111-2222", 1),
                                    (80_000, "220-3333-4444", 0)]:
            db.add(AccountTransaction(account_id=evaluate.A_MAIN, transaction_type="TRANSFER", transaction_direction="OUT",
                                      amount=amount, counterparty_account=number, new_balance=0,
                                      transaction_at=now - timedelta(days=day)))
        db.commit()
    data = chat(client, "저번에 보낸 만큼 엄마한테 보내줘").json()
    assert data["status"] == "confirm"
    assert data["confirm"]["금액"] == 10_000 and data["confirm"]["금액 기준"]
    assert_ledger(engine)
    action = {"thread_id": data["thread_id"], "confirmation_id": data["confirmation_id"]}
    assert confirm(client, action, pin="000000").status_code >= 400
    assert_ledger(engine)
    assert confirm(client, action).json()["status"] == "done"
    assert_ledger(engine, 10_000)


def test_repeat_without_history_asks_instead_of_using_model_amount(bank, monkeypatch):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="TRANSFER")))
    monkeypatch.setattr(agent, "slot_llm", SimpleNamespace(invoke=lambda _: agent.TransferSlots(recipient="엄마", amount=99_000)))
    data = chat(client, "지난번에 보낸 만큼 엄마한테 보내줘").json()
    assert data["status"] == "ask" and data["confirmation_id"] is None
    assert "이 계좌로 보낸 내역이 없어요" in data["blocks"][0]["text"]
    assert_ledger(engine)


def test_limit_links_and_product_comparison(bank, monkeypatch):
    client, engine, _ = bank
    with Session(engine) as db:
        for product in db.scalars(select(AccountProduct)):
            if product.code in product_catalog():
                product.interest_rate = Decimal(str(product_catalog()[product.code]["rate"]))
        db.commit()

    def route(prompt):
        if prompt.endswith("한도 올려줘"):
            return agent.Route(intent="LIMIT_CHANGE")
        if prompt.endswith("파킹통장") and "이체한도를 바꿀지" in prompt:
            return agent.Route(intent="LIMIT_CHANGE", account_hint="파킹통장")
        return agent.Route(intent="PRODUCT_RECOMMENDATION", purpose="savings" if prompt.endswith("잠시 보관하려고") else "general")

    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=route))
    monkeypatch.setattr(agent, "llm", SimpleNamespace(invoke=lambda _: AIMessage(content="보관용으로 비교해 보세요.")))
    limit = chat(client, "한도 올려줘").json()
    assert limit["status"] == "ask"
    selected = chat(client, "파킹통장", thread_id=limit["thread_id"]).json()
    links = next(b["links"] for b in selected["blocks"] if b["kind"] == "links")
    assert [link["to"] for link in links] == [f"/accounts/{evaluate.A_PARK}/manage"]
    pair = chat(client, "입출금통장이 좋을지 파킹통장이 좋을지").json()
    assert pair["status"] == "ask"
    result = chat(client, "잠시 보관하려고", thread_id=pair["thread_id"]).json()
    assert result["status"] == "answered"
    insight = next(b for b in result["blocks"] if b["kind"] == "recommendationInsight")
    assert [candidate["code"] for candidate in insight["items"]] == ["parking", "basic"]


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

    monkeypatch.setattr(agent, "query_llm", SimpleNamespace(bind_tools=lambda _, **kw: SimpleNamespace(invoke=invoke)))
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


@pytest.mark.parametrize("message", ["계좌 정지하고 싶어", "입출금통장을 일시 정지해줘", "내 계좌 좀 막아줘", "카드 말고 계좌 정지해줘"])
def test_account_stop_never_becomes_card_confirmation(bank, monkeypatch, message):
    client, engine, _ = bank
    def unexpected_model_call(_):
        raise AssertionError("명확한 계좌 정지 요청은 모델 없이 안내한다")
    for name in ("router_llm", "card_llm"):
        monkeypatch.setattr(agent, name, SimpleNamespace(invoke=unexpected_model_call))
    data = chat(client, message).json()
    assert data["status"] == "guided" and data["confirmation_id"] is None
    assert data["confirm"] is None
    assert "계좌 정지는 챗봇에서 지원하지 않아요" in data["blocks"][0]["text"]
    assert "계좌 해지" in data["blocks"][0]["text"]
    # 분류기를 우회해 카드 노드를 직접 호출해도 카드 조치로 진행하지 않는다.
    assert agent.card_action({"message": message}, {})["status"] == "guided"
    with Session(engine) as db:
        assert db.get(Card, evaluate.CARD).status == "ACTIVE"
        assert db.get(Account, evaluate.A_MAIN).status == "ACTIVE"


def test_account_linked_card_stop_still_requires_pin(bank, monkeypatch):
    client, engine, _ = bank
    monkeypatch.setattr(agent, "router_llm", SimpleNamespace(invoke=lambda _: agent.Route(intent="CARD_ACTION")))
    monkeypatch.setattr(agent, "card_llm", SimpleNamespace(invoke=lambda _: agent.CardSlots(action="SUSPEND")))
    data = chat(client, "계좌에 연결된 끝자리 4821 카드 정지해줘").json()
    assert data["status"] == "confirm" and data["confirmation_type"] == "CARD_SUSPEND"
    with Session(engine) as db:
        assert db.get(Card, evaluate.CARD).status == "ACTIVE"


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
