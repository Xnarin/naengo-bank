from datetime import date
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from app.agent import evaluate, graph
from app.agent.lite_query import card_followup_args, month_ranges, requested_range
from app.models import Account


def test_month_range_handles_year_boundary_and_preserves_explicit_dates():
    ranges = month_ranges(date(2026, 1, 9))
    assert requested_range("지난달 1일부터 말일까지", ranges, None) == ("2025-12-01", "2025-12-31")
    assert requested_range("이번 달 1일부터 오늘까지", ranges, None) == ("2026-01-01", "2026-01-09")
    for message in ("지난달 1일 결제", "지난달 둘째 주", "지난달 15일부터", "같은 기간 대신 2024년 3월"):
        previous = {"start": "2025-12-01", "end": "2025-12-31"}
        assert requested_range(message, ranges, previous) is None


def test_lite_query_cannot_answer_amount_without_tool_result(monkeypatch):
    def bind_tools(_, *, tool_choice=None):
        def invoke(_):
            assert tool_choice == "required"
            return AIMessage(content="잔액은 999,999원이에요.")
        return SimpleNamespace(invoke=invoke)

    monkeypatch.setattr(graph, "query_llm", SimpleNamespace(bind_tools=bind_tools))
    with evaluate.seed() as db:
        result = graph.lite_account_query({"message": "지난달 카드 결제 합계 알려줘"}, {
            "configurable": {"db": db, "user_id": evaluate.ME},
        })
    assert "999,999원" not in result["answer"]
    assert "조회 결과를 확인하지 못했어요" in result["answer"]
    assert result["last_card_query"] is None


def test_lite_simple_balance_uses_owned_account_and_renders_ledger_amount(monkeypatch):
    monkeypatch.setattr(graph, "query_llm", None)
    with evaluate.seed() as db:
        db.get(Account, evaluate.A_MAIN).nickname = "급여통장"
        result = graph.lite_account_query(
            {"message": "내 급여통장에 남은 돈이 얼마야?", "account_hint": "내 급여통장에"},
            {"configurable": {"db": db, "user_id": evaluate.ME}},
        )
    assert result["answer"] == "급여통장 잔액은 1,284,500원이에요."


def test_card_followup_changes_only_the_requested_filter():
    previous = {"start": "2026-01-01", "end": "2026-01-09", "category": "카페"}
    assert card_followup_args("그럼 지난달은?", ("2025-12-01", "2025-12-31"), previous) == {
        "start": "2025-12-01", "end": "2025-12-31", "category": "카페",
    }
    message = "같은 기간 이번엔 쇼핑은? 내역이 없다면 없다고 알려줘."
    period = requested_range(message, month_ranges(date(2026, 1, 9)), previous)
    assert card_followup_args(message, period, previous) == {**previous, "category": "쇼핑"}
    assert card_followup_args("같은 기간 급여 입금은?", period, previous) is None
