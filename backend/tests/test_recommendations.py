from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.agent.insight_blocks import insight_block
from app.agent.tools import make_tools
from app.errors import BankError
from app.models import AccountProduct, AccountTransaction
from app.services import recommendations
from app.services.recommendations import product_catalog, recommend_accounts
from test_insights import AT, bank  # noqa: F401


@pytest.fixture
def catalog_bank(bank):
    db, *_ = bank
    for code, spec in product_catalog().items():
        product = db.scalar(select(AccountProduct).where(AccountProduct.code == code))
        if product is None:
            product = AccountProduct(code=code)
            db.add(product)
        product.product_name = spec["name"]
        product.interest_rate = Decimal(str(spec["rate"]))
    db.commit()
    return bank


def test_recommendation_uses_spending_and_shortfall_without_moving_money(catalog_bank):
    db, me, _, account, *_ = catalog_bank
    account.balance = 1000
    db.commit()
    count = db.scalar(select(func.count()).select_from(AccountTransaction))
    report = recommend_accounts(db, me.id, at=AT)
    assert report["상태"] == "소비패턴기준비교"
    assert report["분석"]["카드소비"] == 15_000
    assert report["분석"]["예상부족액"] == 6500
    assert report["추천"][0]["code"] == "living"
    assert not any(row["code"] in ("youth", "parking", "group") for row in report["추천"])
    assert any("15,000원" in reason for reason in report["추천"][0]["reasons"])
    assert next(row for row in report["추천"] if row["code"] == "basic")["owned"] is True
    assert account.balance == 1000
    assert db.scalar(select(func.count()).select_from(AccountTransaction)) == count


def test_cold_user_is_not_personalized_and_explicit_purpose_can_be_compared(catalog_bank):
    db, _, other, *_ = catalog_bank
    cold = recommend_accounts(db, other.id, at=AT)
    assert cold["상태"] == "데이터부족" and cold["추천"] == []
    assert cold["추가질문"]
    assert cold["분석"]["카드소비"] == 0
    assert cold["분석"]["월말예상잔액"] is None
    savings = recommend_accounts(db, other.id, "savings", at=AT)
    assert savings["상태"] == "목적기준안내"
    assert savings["추천"][0]["code"] == "parking"
    assert all("관측" not in reason for row in savings["추천"] for reason in row["reasons"])
    group = recommend_accounts(db, other.id, "group", at=AT)
    assert group["추천"][0]["code"] == "group"


def test_youth_is_only_candidate_when_recorded_age_fits(catalog_bank):
    db, me, *_ = catalog_bank
    assert all(row["code"] != "youth" for row in recommend_accounts(db, me.id, at=AT)["추천"])
    me.birth = date(2000, 1, 1)
    db.commit()
    assert any(row["code"] == "youth" for row in recommend_accounts(db, me.id, at=AT)["추천"])
    me.birth = date(1980, 1, 1)
    db.commit()
    assert all(row["code"] != "youth" for row in recommend_accounts(db, me.id, at=AT)["추천"])


def test_catalog_conditions_match_ui_and_rate_mismatch_is_not_recommended(catalog_bank):
    db, me, *_ = catalog_bank
    report = recommend_accounts(db, me.id, "spending", at=AT)
    living = report["추천"][0]
    assert living["code"] == "living"
    assert living["conditions"] == product_catalog()["living"]["conditions"]
    assert living["rateTable"] == product_catalog()["living"]["rateTable"]
    db.scalar(select(AccountProduct).where(AccountProduct.code == "living")).interest_rate = Decimal("9.9")
    db.commit()
    assert all(row["code"] != "living" for row in recommend_accounts(db, me.id, "spending", at=AT)["추천"])


def test_tool_identity_and_recommendation_card_use_same_scoped_result(catalog_bank, monkeypatch):
    db, me, other, *_ = catalog_bank
    monkeypatch.setattr(recommendations, "now_kst", lambda: AT)
    tool = next(tool for tool in make_tools(db, me.id) if tool.name == "recommend_accounts")
    report = tool.invoke({"user_id": str(other.id), "purpose": "spending"})
    assert report["분석"]["현재총잔액"] == 50_000
    block = insight_block("recommend_accounts", report)
    assert block["items"][0]["code"] == report["추천"][0]["code"]
    assert "score" not in block["items"][0]
    with pytest.raises(BankError):
        recommend_accounts(db, me.id, "invest", at=AT)


def test_recommendation_node_always_reads_data_and_cold_user_gets_choices(catalog_bank, monkeypatch):
    from importlib import import_module
    from langchain_core.messages import AIMessage
    graph = import_module("app.agent.graph")
    db, me, other, *_ = catalog_bank
    monkeypatch.setattr(recommendations, "now_kst", lambda: AT)
    messages = []

    class Model:
        def invoke(self, prompt):
            messages.append(prompt[-1].content)
            return AIMessage(content="기록과 사용 목적을 기준으로 비교해 주세요.")

    monkeypatch.setattr(graph, "llm", Model())
    result = graph.product_recommendation({"message": "통장 추천", "recommendation_purpose": "spending"},
                                           {"configurable": {"db": db, "user_id": me.id}})
    assert result["blocks"][0]["items"][0]["code"] == "living"
    assert "15000" in messages[0]
    cold = graph.product_recommendation({"message": "통장 추천"}, {"configurable": {"db": db, "user_id": other.id}})
    assert cold["blocks"][0]["items"] == [] and cold["blocks"][1]["kind"] == "choices"
    assert len(cold["blocks"][1]["options"]) == 3


def test_recommendation_requires_login_before_analysis(monkeypatch):
    from importlib import import_module
    graph = import_module("app.agent.graph")

    class Router:
        def invoke(self, prompt):
            return graph.Route(intent="PRODUCT_RECOMMENDATION", purpose="general")

    monkeypatch.setattr(graph, "router_llm", Router())
    state = graph.router({"message": "입출금통장 추천"}, {"configurable": {"user_id": None}})
    assert state["status"] == "guided" and graph.after_router(state) == "need_login"
