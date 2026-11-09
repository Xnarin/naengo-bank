"""Synthetic spending and subscription history for demo accounts."""
from datetime import datetime, time

from sqlalchemy import select

from app.models import KST, AccountTransaction, Card, CardPayment
from app.services.cards import new_card
from app.services.insights import month_start
from app.services.verification import aware

TAG = "가상 분석데이터 v1"


def add_demo_history(db, user, account, now):
    card = db.scalar(select(Card).where(Card.account_id == account.id, Card.status == "ACTIVE").order_by(Card.created_at))
    if card is None:
        card = new_card(account.id, 1_000_000, False)
        db.add(card)
        db.flush()
    seeded_start = datetime.combine(month_start(now.date(), -3), time(8), KST)
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
        events.extend([(23, 14_900, "StreamFlix", "구독"), (25, 10_900, "CloudMusic", "구독"),
                       (26, 2900, "CloudDrive", "구독"), (15, 90_000 + index * 45_000, "가상 쇼핑몰", "쇼핑"),
                       (24, 150_000 + index * 60_000, "가상 백화점", "쇼핑"), (3, 650_000, "가상 월세", None)])
        total = sum(event[1] for event in events)
        running = total
        db.add(AccountTransaction(account_id=account.id, transaction_type="DEPOSIT", transaction_direction="IN",
                                  amount=total, new_balance=running, counterparty_name="가상 급여", memo=TAG,
                                  transaction_at=datetime.combine(month, time(8), KST)))
        ledger = []
        for sequence, (day, amount, place, category) in enumerate(sorted(events)):
            when = datetime.combine(month.replace(day=day), time(10, sequence), KST)
            payment = None
            if category:
                payment = CardPayment(card_id=card.id, amount=amount, place=place, category=category, overseas=False,
                                      idempotency_key=f"insight-seed-v1:{month}:{sequence}", request_at=when, complete_at=when)
                db.add(payment)
            ledger.append((when, amount, place, payment))
        db.flush()
        for when, amount, place, payment in ledger:
            running -= amount
            assert running >= 0
            db.add(AccountTransaction(account_id=account.id, card_payment_id=payment.id if payment else None,
                                      transaction_type="CARD" if payment else "WITHDRAW", transaction_direction="OUT",
                                      amount=amount, new_balance=running, counterparty_name=place, memo=TAG, transaction_at=when))
        assert running == 0
        summaries.append({"month": month.strftime("%Y-%m"), "synthetic_in": total, "synthetic_out": total})
    return summaries
