from importlib import import_module

from langchain_core.messages import AIMessage

from app.agent.insight_blocks import insight_block
from app.services import insights
from test_insights import AT, bank  # noqa: F401 — reuse the isolated banking fixture


def test_visuals_use_calculation_results_and_do_not_fake_insufficient_forecasts(bank):
    db, me, other, *_ = bank
    spending = insights.spending_analysis(db, me.id, at=AT)
    block = insight_block("spending_analysis", spending)
    assert block["kind"] == "spendingInsight"
    assert block["total"] == 6000 and sum(row["amount"] for row in block["categories"]) == 6000
    forecast = insights.balance_forecast(db, me.id, at=AT)
    block = insight_block("balance_forecast", forecast)
    assert block["points"][-1]["balance"] == block["projectedBalance"]
    assert block["points"][0]["balance"] == block["balance"]
    cold = insight_block("balance_forecast", insights.balance_forecast(db, other.id, at=AT))
    assert cold["sufficient"] is False
    assert "points" not in cold and "projectedBalance" not in cold and "estimatedExpense" not in cold
    assert insight_block("balance_forecast", "오류: 기간을 확인해 주세요") is None
    assert insight_block("list_accounts", []) is None


def test_subscription_and_card_spending_visuals_preserve_scope_and_period(bank):
    db, me, _, _, _, _, _, outgoing = bank
    for day in ("2026-08-31", "2026-09-30", "2026-10-31"):
        outgoing(day, 15_000, "ViewFlix")
    block = insight_block("detect_subscriptions", insights.detect_subscriptions(db, me.id, at=AT))
    assert block["items"][0]["name"] == "ViewFlix" and block["items"][0]["billingDay"] == 31
    assert block["total"] == sum(row["amount"] for row in block["items"])
    card = insight_block("card_spending", {"합계": 9000, "카테고리별": {"카페": 3000, "식비": 6000}},
                         {"start": "2026-11-01", "end": "2026-11-15"})
    assert card["categories"][0] == {"label": "식비", "amount": 6000}
    assert card["start"] == "2026-11-01" and card["total"] == card["cardTotal"]
    assert "comparison" not in card


def test_graph_attaches_server_charts_and_does_not_reuse_old_charts(bank, monkeypatch):
    graph = import_module("app.agent.graph")
    db, me, *_ = bank
    monkeypatch.setattr(insights, "now_kst", lambda: AT)

    class Model:
        def __init__(self, name, args):
            self.messages = iter([AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call-1"}]),
                                  AIMessage(content="계산 결과를 확인해 주세요.")])

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return next(self.messages)

    config = {"configurable": {"db": db, "user_id": me.id}}
    monkeypatch.setattr(graph, "query_llm", Model("spending_analysis", {}))
    first = graph.account_query({"message": "소비 분석"}, config)
    assert first["blocks"][0]["kind"] == "spendingInsight" and first["blocks"][0]["total"] == 6000
    monkeypatch.setattr(graph, "query_llm", Model("list_accounts", {}))
    assert graph.account_query({"message": "잔액", "blocks": first["blocks"]}, config)["blocks"] == []
    monkeypatch.setattr(graph, "query_llm", Model("spending_analysis", {"month": "invalid"}))
    assert graph.account_query({"message": "소비 분석"}, config)["blocks"] == []


def test_answer_drops_sentences_pointing_at_screen_cards():
    from app.agent.graph import drop_screen_refs
    text = ("테스트1통장의 잔액은 1,050,000원이에요.\n\n자세한 계좌 정보는 화면의 요약 카드에서 확인하실 수 있어요.\n\n"
            "- 11-05: 입금 50,000원\n- 11-04: 출금 3,000원\n\n전체 내역은 화면의 목록과 요약 카드에서 바로 확인하실 수 있어요.")
    out = drop_screen_refs(text)
    assert "카드" not in out and "화면" not in out
    assert out.startswith("테스트1통장의 잔액은 1,050,000원이에요.")
    assert "- 11-05: 입금 50,000원\n- 11-04: 출금 3,000원" in out
    assert "\n\n\n" not in out
    # 체크카드처럼 화면 안내가 아닌 '카드'는 남긴다
    assert drop_screen_refs("체크카드로 32,000원을 썼어요.") == "체크카드로 32,000원을 썼어요."
