"""개발 환경에서만 수동 실행하는 UI 체험 계정. 실제 이메일을 발송하지 않는다."""
import secrets
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Account, Card, CardPayment, Term, VerificationCode, now_kst
from app.security import hash_secret
from app.services import accounts, auth, cards, transfers


def main():
    if not settings.development:
        raise RuntimeError("개발 환경에서만 실행할 수 있습니다.")
    with SessionLocal() as db:
        def member(email, name, password, pin):
            user = auth.find_by_email(db, email)
            if user:
                if user.status != "ACTIVE":
                    raise RuntimeError("기존 체험 계정 상태는 자동으로 변경하지 않습니다.")
                return user
            db.add(VerificationCode(email=email, purpose="SIGNUP", code_hash=hash_secret(secrets.token_urlsafe(24)),
                expires_at=now_kst() + timedelta(minutes=3), verified_at=now_kst()))
            db.commit()
            terms = list(db.scalars(select(Term.id).where(Term.category == "SIGNUP")))
            return auth.signup(db, email=email, user_name=name, password=password, pin=pin, phone_num=None, agreed_term_ids=terms)
        demo = member("test1@example.com", "테스트하나", "Test1234!", "493827")
        friend = member("test2@example.com", "테스트두리", "Test1234!", "493827")
        source = db.scalar(select(Account).where(Account.user_id == demo.id, Account.status == "ACTIVE").order_by(Account.created_at))
        target = db.scalar(select(Account).where(Account.user_id == friend.id, Account.status == "ACTIVE").order_by(Account.created_at))
        if source is None or target is None:
            raise RuntimeError("체험 계좌가 해지되어 자동 초기화하지 않습니다.")
        source.nickname = "생활비통장"
        db.commit()
        if len(db.scalars(select(Account.id).where(Account.user_id == demo.id)).all()) < 2:
            terms = list(db.scalars(select(Term.id).where(Term.category == "ACCOUNT_OPEN")))
            accounts.open_account(db, demo.id, product_code="parking", password="5849", password_confirm="5849",
                opening_info={"purpose": "비상금"}, nickname="비상금통장", agreed_term_ids=terms)
        transfers.add_favorite(db, demo.id, target.account_num, "테스트두리")
        transfers.transfer(db, source.id, target.id, 10_000, "demo-initial-transfer-v1", "체험 송금")
        card = db.scalar(select(Card).where(Card.account_id == source.id, Card.status.in_(("ACTIVE", "SUSPENDED", "LOST"))))
        if card is None:
            issued = cards.issue(db, demo.id, source.id, 1_000_000, False)
            card = db.get(Card, issued["id"])
        if card.status == "ACTIVE" and not db.scalar(select(CardPayment.id).where(CardPayment.card_id == card.id).limit(1)):
            cards.pay(db, demo.id, card.id, 1800, "체험카페", "카페", False, "demo-initial-payment-v1")
        print("Development demo account ready. Existing user data was preserved; no emails sent.")


if __name__ == "__main__":
    main()
