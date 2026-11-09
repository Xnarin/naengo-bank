"""사용자가 요청한 test1 전용 가상 분석 내역. 현재 잔액·기존 거래·다른 회원은 유지한다."""
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import KST, Account, AccountTransaction, User, now_kst
from app.services.demo_history import TAG, add_demo_history
from app.services.insights import balance_forecast, detect_subscriptions, month_start, spending_analysis


def main():
    if not settings.development:
        raise RuntimeError("개발 환경에서만 실행할 수 있습니다.")
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == "test1@example.com", User.status == "ACTIVE").with_for_update())
        assert user, "test1 계정이 필요합니다."
        account = db.scalar(select(Account).where(Account.user_id == user.id, Account.status == "ACTIVE")
                            .order_by(Account.created_at, Account.id).with_for_update())
        assert account, "정상 계좌가 필요합니다."
        original_balance = account.balance
        if db.scalar(select(AccountTransaction.id).join(Account).where(Account.user_id == user.id, AccountTransaction.memo == TAG).limit(1)):
            print("Synthetic analysis history already exists; no duplicate rows added.")
            return
        now = now_kst()
        first_existing = db.scalar(select(func.min(AccountTransaction.transaction_at)).where(AccountTransaction.account_id == account.id))
        # 가상 기록은 기존 거래보다 앞에 붙이고 월별 잔액을 0원으로 끝낸다.
        if first_existing:
            from app.services.verification import aware
            assert aware(first_existing).astimezone(KST).date() >= month_start(now.date()), "기존 과거 거래가 있어 자동 추가를 중단합니다."
        summaries = add_demo_history(db, user, account, now)
        db.flush()
        assert account.balance == original_balance
        net = sum(t.amount if t.transaction_direction == "IN" else -t.amount for t in db.scalars(
            select(AccountTransaction).where(AccountTransaction.account_id == account.id, AccountTransaction.memo == TAG)))
        assert net == 0
        subscriptions = detect_subscriptions(db, user.id, at=now)
        assert {row["가맹점"] for row in subscriptions["후보"]} == {"StreamFlix", "CloudMusic", "CloudDrive"}
        forecast = balance_forecast(db, user.id, at=now)
        assert forecast["상태"] == "예측완료"
        print({"history": summaries, "balance_preserved": original_balance, "subscription_candidates": len(subscriptions["후보"]),
               "latest_month_spending": spending_analysis(db, user.id, month_start(now.date(), -1).strftime("%Y-%m"))["전체출금"],
               "forecast_status": forecast["상태"]})


if __name__ == "__main__":
    main()
