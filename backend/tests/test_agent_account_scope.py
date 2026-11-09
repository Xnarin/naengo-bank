from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent import evaluate, graph, tools
from app.errors import BankError
from app.models import Account


@pytest.mark.parametrize(("message", "hint", "status", "expected"), [
    ("220-1111-2222 계좌 잔액 알려줘", "220-1111-2222", "answered", "본인 계좌만 조회할 수 있어요."),
    ("22011112222 계좌 거래내역 알려줘", "22011112222", "answered", "본인 계좌만 조회할 수 있어요."),
    ("440-9999-9999 계좌 잔액 알려줘", "440-9999-9999", "answered", "본인 계좌만 조회할 수 있어요."),
    ("여행적금 잔액만 알려줘", "여행적금", "answered", "요청하신 계좌를 찾을 수 없어요."),
    ("통장 잔액 알려줘", "통장", "ask", "어느 계좌인지"),
])
def test_unresolved_account_stops_before_binding_model_tools(monkeypatch, message, hint, status, expected):
    def route(prompt):
        if graph.ACCOUNT_NUMBER.fullmatch(hint):
            assert hint not in prompt
            return graph.Route(intent="ACCOUNT_QUERY", account_hint="[계좌번호1]")
        return graph.Route(intent="ACCOUNT_QUERY", account_hint=hint)

    monkeypatch.setattr(graph, "router_llm", SimpleNamespace(invoke=route))

    def unexpected_tools(*args, **kwargs):
        pytest.fail("Account data tools must not be available when the target was not resolved.")

    monkeypatch.setattr(tools, "make_tools", unexpected_tools)
    with evaluate.seed() as db:
        state = graph.run(message, db=db, user_id=evaluate.ME)
    assert state["status"] == status
    assert state["answer"].startswith(expected)
    assert state["blocks"] == []


def test_scoped_tools_cannot_expand_an_owned_account_lookup():
    with evaluate.seed() as db:
        target, = tools.match_accounts(db, evaluate.ME, "110-4823-0591")
        read = {tool.name: tool for tool in tools.make_tools(db, evaluate.ME, account=target)}
        assert [row["잔액"] for row in read["list_accounts"].invoke({})] == [1_284_500]
        assert "회비" in read["get_transactions"].invoke({"account": "전체"})
        with pytest.raises(BankError, match="계좌를 찾을 수 없어요"):
            read["get_transactions"].invoke({"account": "생활비"})


def test_owned_account_reference_is_resolved_without_sending_raw_number(monkeypatch):
    number = "110-4823-0591"
    monkeypatch.setattr(graph, "router_llm", SimpleNamespace(
        invoke=lambda _: graph.Route(intent="ACCOUNT_QUERY", account_hint="[계좌번호1]")))

    def invoke(messages):
        assert all(number not in message.content for message in messages)
        if isinstance(messages[-1], ToolMessage):
            result = messages[-1].content
            assert "110-****-0591" in result
            assert "1284500" in result and "5020000" not in result
            return AIMessage(content="잔액은 1,284,500원이에요.")
        assert "[계좌번호1]" in messages[-1].content
        return AIMessage(content="", tool_calls=[{"name": "list_accounts", "args": {}, "id": "accounts"}])

    monkeypatch.setattr(graph, "llm", SimpleNamespace(bind_tools=lambda _: SimpleNamespace(invoke=invoke)))
    with evaluate.seed() as db:
        db.get(Account, evaluate.A_MAIN).nickname = number
        state = graph.run(f"{number} 계좌 잔액 알려줘", db=db, user_id=evaluate.ME)
    assert state["answer"] == "잔액은 1,284,500원이에요."
