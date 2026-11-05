"""사용자가 요청한 test1 전용 가상 분석 내역. 현재 잔액·기존 거래·다른 회원은 유지한다."""
from datetime import datetime, time

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import KST, Account, AccountTransaction, Card, CardPayment, User, now_kst
from app.services.cards import new_card
from app.services.insights import balance_forecast, detect_subscriptions, month_start, spending_analysis

TAG = "가상 분석데이터 v1"


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
        card = db.scalar(select(Card).where(Card.account_id == account.id, Card.status == "ACTIVE").order_by(Card.created_at))
        if card is None:
            card = new_card(account.id, 1_000_000, False)
            db.add(card)
            db.flush()
        seeded_start = datetime.combine(month_start(now.date(), -3), time(8), KST)
        from app.services.verification import aware
        account.created_at = min(aware(account.created_at), seeded_start)
        user.created_at = min(aware(user.created_at), seeded_start)
        card.created_at = min(aware(card.created_at), seeded_start)
        summaries = []
        for index, offset in enumerate((-3, -2, -1)):
            month = month_start(now.date(), offset)
            events = []
            for day in range(1, 26):
                events.append((day, 9000 + index * 1500, "가상 식당", "식비"))
            for day in (2, 5, 8, 11, 14, 17, 20, 23, 26):
                events.append((day, 4500 + index * 500, "가상 카페", "카페"))
            for day in (5, 12, 19, 26):
                events.append((day, 65_000 + index * 5000, "가상 마트", "장보기"))
            events.extend([(8, 14_900, "StreamFlix", "구독"), (12, 10_900, "CloudMusic", "구독"),
                           (20, 2900, "CloudDrive", "구독"), (15, 90_000 + index * 45_000, "가상 쇼핑몰", "쇼핑"),
                           (24, 150_000 + index * 60_000, "가상 백화점", "쇼핑"), (3, 650_000, "가상 월세", None)])
            total = sum(event[1] for event in events)
            running = total
            db.add(AccountTransaction(account_id=account.id, transaction_type="DEPOSIT", transaction_direction="IN",
                                      amount=total, new_balance=running, counterparty_name="가상 급여", memo=TAG,
                                      transaction_at=datetime.combine(month, time(8), KST)))
            for sequence, (day, amount, place, category) in enumerate(sorted(events)):
                when = datetime.combine(month.replace(day=day), time(10, sequence), KST)
                payment = None
                if category:
                    payment = CardPayment(card_id=card.id, amount=amount, place=place, category=category, overseas=False,
                                          idempotency_key=f"insight-seed-v1:{month}:{sequence}", request_at=when, complete_at=when)
                    db.add(payment)
                    db.flush()
                running -= amount
                assert running >= 0
                db.add(AccountTransaction(account_id=account.id, card_payment_id=payment.id if payment else None,
                                          transaction_type="CARD" if payment else "WITHDRAW", transaction_direction="OUT",
                                          amount=amount, new_balance=running, counterparty_name=place, memo=TAG, transaction_at=when))
            assert running == 0
            summaries.append({"month": month.strftime("%Y-%m"), "synthetic_in": total, "synthetic_out": total})
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
