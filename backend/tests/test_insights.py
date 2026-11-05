from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import KST, Account, AccountProduct, AccountTransaction, AutoTransfer, Base, Card, CardPayment, User
from app.services.insights import balance_forecast, detect_subscriptions, spending_analysis

AT = datetime(2026, 11, 15, 12, tzinfo=KST)


@pytest.fixture
def bank():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        me = User(email="mine@example.com", user_name="나", password_hash="x", pin="x")
        other = User(email="other@example.com", user_name="다른사람", password_hash="x", pin="x")
        product = AccountProduct(code="basic", product_name="통장")
        db.add_all([me, other, product])
        db.flush()
        account = Account(user_id=me.id, product_id=product.id, account_num="111-1111-1111", account_password="x", balance=50_000)
        parking = Account(user_id=me.id, product_id=product.id, account_num="222-2222-2222", account_password="x", balance=0)
        target = Account(user_id=other.id, product_id=product.id, account_num="333-3333-3333", account_password="x", balance=9_000_000)
        db.add_all([account, parking, target])
        db.flush()
        card = Card(account_id=account.id, card_number="unused", expiry_date="12/29")
        db.add(card)
        db.flush()

        def outgoing(day, amount=3000, place="카페", kind="CARD", direction="OUT", counterparty=None):
            when = datetime.combine(date.fromisoformat(day), datetime.min.time(), KST)
            payment = None
            if kind == "CARD":
                payment = CardPayment(card_id=card.id, amount=amount, place=place, category="카페", request_at=when, complete_at=when)
                db.add(payment)
                db.flush()
            db.add(AccountTransaction(account_id=account.id, card_payment_id=payment.id if payment else None,
                                      transaction_type=kind, transaction_direction=direction, amount=amount,
                                      new_balance=0, counterparty_account=counterparty, transaction_at=when))
            db.flush()

        for day in ("2026-10-16", "2026-10-20", "2026-10-25", "2026-11-01", "2026-11-10"):
            outgoing(day)
        db.commit()
        yield db, me, other, account, parking, target, card, outgoing
    engine.dispose()


def test_spending_compares_same_days_and_excludes_internal_transfers(bank):
    db, me, _, _, parking, _, card, outgoing = bank
    outgoing("2026-10-10", 5000)
    outgoing("2026-11-05", 4000, kind="TRANSFER", counterparty="333-3333-3333")
    outgoing("2026-11-06", 100_000, kind="TRANSFER", counterparty=parking.account_num)
    card.status = "CANCELED"  # historical consumption still counts
    db.commit()
    report = spending_analysis(db, me.id, at=AT)
    assert report["전체출금"] == 10_000
    assert report["카드소비"] == 6000
    assert report["용도미확정_이체등출금"] == 4000
    assert report["비교기간"]["출금"] == 5000
    assert report["비교기간"]["종료일"] == "2026-10-15"
    assert report["비교기간대비증감액"] == 5000
    assert report["분류별"][0]["금액"] == 6000


def test_forecast_counts_schedules_once_and_excludes_own_transfers(bank):
    db, me, _, account, parking, target, _, _ = bank
    for destination in (target, parking):
        db.add(AutoTransfer(from_account_id=account.id, to_account_id=destination.id, amount=10_000,
                            cycle="MONTHLY", run_day=20, start_date=date(2026, 11, 1),
                            next_run_at=datetime(2026, 11, 20, 9, tzinfo=KST)))
    db.commit()
    report = balance_forecast(db, me.id, at=AT)
    assert report["상태"] == "예측완료"
    assert report["현재총잔액"] == 50_000
    assert report["관측일수"] == 30 and report["관측변동출금"] == 15_000
    assert report["예정지출합계"] == 10_000
    assert report["남은기간예상출금"] == 17_500
    assert report["대상월예상출금"] == 23_500
    assert report["월말예상잔액"] == 32_500
    assert report["예상부족액"] == 0
    assert report["잔액추이"][0] == {"날짜": "2026-11-15", "잔액": 50_000}
    assert report["잔액추이"][-1] == {"날짜": "2026-11-30", "잔액": report["월말예상잔액"]}
    following = balance_forecast(db, me.id, "2026-12", at=AT)
    assert following["예정지출합계"] == 20_000
    assert following["대상월예상출금"] == 25_500
    assert following["월말예상잔액"] == 7000
    assert following["잔액추이"][-1]["잔액"] == following["월말예상잔액"]
    assert account.balance == 50_000  # read tools never move money


def test_subscription_candidates_handle_month_end_and_not_double_count(bank):
    db, me, _, _, _, _, _, outgoing = bank
    for day in ("2026-08-31", "2026-09-30", "2026-10-31"):
        outgoing(day, 15_000, "ViewFlix")
    for day in ("2026-10-25", "2026-11-01", "2026-11-08"):
        outgoing(day, 5000, "매주 방문 카페")
    db.commit()
    report = detect_subscriptions(db, me.id, at=AT)
    assert len(report["후보"]) == 1
    assert report["후보"][0]["가맹점"] == "ViewFlix"
    assert report["월예상합계"] == 15_000
    forecast = balance_forecast(db, me.id, "2026-12", at=AT)
    subscriptions = [row for row in forecast["예정지출"] if row["종류"] == "정기결제 후보"]
    assert [row["날짜"] for row in subscriptions] == ["2026-11-30", "2026-12-31"]
    assert forecast["관측변동출금"] == 30_000  # subscription charges are excluded from the daily average


def test_insufficient_data_and_owner_scope(bank):
    db, _, other, _, _, target, _, _ = bank
    report = balance_forecast(db, other.id, at=AT)
    assert report["상태"] == "데이터부족"
    assert "월말예상잔액" not in report and "대상월예상출금" not in report
    assert "잔액추이" not in report
    assert report["현재총잔액"] == target.balance
    assert detect_subscriptions(db, other.id, at=AT)["후보"] == []
    assert spending_analysis(db, other.id, at=AT)["전체출금"] == 0


def test_forecast_shortfall_and_cancelled_expired_schedules(bank):
    db, me, _, account, _, target, _, _ = bank
    account.balance = 1000
    for status, end in (("CANCELED", None), ("ACTIVE", date(2026, 11, 14))):
        db.add(AutoTransfer(from_account_id=account.id, to_account_id=target.id, amount=90_000,
                            cycle="ONCE", start_date=date(2026, 11, 1), end_date=end, status=status,
                            next_run_at=AT - timedelta(days=2)))
    db.commit()
    report = balance_forecast(db, me.id, at=AT)
    assert report["예정지출합계"] == 0
    assert report["월말예상잔액"] == -6500 and report["예상부족액"] == 6500
    assert report["잔액하한시나리오"] <= report["월말예상잔액"] <= report["잔액상한시나리오"]


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "bad", "2026-09", "2027-01"])
def test_forecast_rejects_invalid_or_unsupported_month(bank, month):
    db, me, *_ = bank
    with pytest.raises(BankError):
        balance_forecast(db, me.id, month, at=AT)


def test_variable_amounts_and_future_charges_are_not_subscriptions(bank):
    db, me, _, _, _, _, _, outgoing = bank
    for day, amount in (("2026-08-10", 1000), ("2026-09-10", 2000), ("2026-10-10", 3000)):
        outgoing(day, amount, "변동 결제")
    outgoing("2026-11-16", 999_999, "미래 결제")
    db.commit()
    assert detect_subscriptions(db, me.id, at=AT)["후보"] == []
    assert spending_analysis(db, me.id, at=AT)["전체출금"] == 6000


def test_calendar_boundary_and_full_previous_month(bank):
    db, me, *_ = bank
    at = datetime(2026, 12, 1, tzinfo=KST)
    previous = spending_analysis(db, me.id, "2026-11", at=at)
    assert previous["비교기간"]["종료일"] == "2026-10-31"
    assert previous["전체출금"] == 6000 and previous["비교기간대비증감액"] == -3000
    following = balance_forecast(db, me.id, "2027-01", at=at)
    assert following["대상월예측일수"] == 31


def test_month_end_curve_includes_same_day_pending_transfer(bank):
    db, me, _, account, _, target, *_ = bank
    db.add(AutoTransfer(from_account_id=account.id, to_account_id=target.id, amount=10_000, cycle="ONCE",
                        start_date=date(2026, 11, 1), next_run_at=datetime(2026, 11, 30, 13, tzinfo=KST)))
    db.commit()
    report = balance_forecast(db, me.id, at=datetime(2026, 11, 30, 12, tzinfo=KST))
    assert report["잔액추이"] == [{"날짜": "2026-11-30", "잔액": 50_000}, {"날짜": "2026-11-30", "잔액": 40_000}]
    assert report["잔액추이"][-1]["잔액"] == report["월말예상잔액"]


def test_tool_identity_is_fixed_by_login_not_model_arguments(bank, monkeypatch):
    from app.agent.tools import make_tools
    from app.services import insights
    db, me, other, *_ = bank
    monkeypatch.setattr(insights, "now_kst", lambda: AT)
    tools = {tool.name: tool for tool in make_tools(db, me.id)}
    assert all("user_id" not in tool.get_input_schema().model_json_schema().get("properties", {}) for tool in tools.values())
    report = tools["spending_analysis"].invoke({"user_id": str(other.id)})
    assert report["카드소비"] == 6000
    assert "9,000,000" not in str(report)
