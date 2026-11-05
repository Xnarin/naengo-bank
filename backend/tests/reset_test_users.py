"""개발 DB의 회원 데이터를 테스트 계정 2개로 교체한다. 실행 전에 DB 백업과 API 중지가 필요하다."""
import sys

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import Account, AccountProduct, AccountTransaction, Base, FavoriteRecipient, Term, TermAgreement, User
from app.security import hash_secret, verify_secret


def main():
    if not settings.development or sys.argv[1:] != ["--reset-users"]:
        raise RuntimeError("개발 환경에서 --reset-users를 명시해야 실행할 수 있습니다.")
    user_tables = {
        "users", "term_agreements", "verification_codes", "login_histories", "notifications",
        "accounts", "account_transactions", "statement_requests", "transfers", "auto_transfers",
        "favorite_recipients", "cards", "card_payments",
    }
    assert set(Base.metadata.tables) == user_tables | {"terms", "account_products"}
    with SessionLocal.begin() as db:
        product = db.scalar(select(AccountProduct).where(AccountProduct.code == "basic"))
        terms = db.scalars(select(Term).where(Term.category == "SIGNUP")).all()
        assert product and terms, "상품·약관 초기 데이터가 필요합니다."
        previous_users = set(db.scalars(select(User.id)))
        for table in reversed(Base.metadata.sorted_tables):
            if table.name in user_tables:
                db.execute(table.delete())

        accounts = []
        password_hash, pin_hash, account_hash = (hash_secret(value) for value in ("Test1234!", "493827", "5849"))
        for index, name, number in [(1, "테스트하나", "111-1111-1111"), (2, "테스트두리", "222-2222-2222")]:
            user = User(email=f"test{index}@example.com", user_name=name, password_hash=password_hash, pin=pin_hash)
            db.add(user)
            db.flush()
            db.add_all([TermAgreement(user_id=user.id, term_id=t.id, agreed=t.required) for t in terms])
            account = Account(user_id=user.id, product_id=product.id, account_num=number,
                              account_password=account_hash, nickname=f"테스트{index}통장", balance=1_000_000)
            db.add(account)
            db.flush()
            db.add(AccountTransaction(account_id=account.id, transaction_type="DEPOSIT", transaction_direction="IN",
                                      amount=1_000_000, new_balance=1_000_000, counterparty_name="내금고", memo="테스트 가상머니"))
            accounts.append((user, account))
        for (sender, _), (recipient, target) in (accounts, accounts[::-1]):
            db.add(FavoriteRecipient(user_id=sender.id, account_num=target.account_num,
                                     holder_name=recipient.user_name, alias=recipient.user_name))
        db.flush()
        assert set(db.scalars(select(User.id))).isdisjoint(previous_users)
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.scalar(select(func.count()).select_from(Account)) == 2
        assert db.scalar(select(func.count()).select_from(AccountTransaction)) == 2
        for name in user_tables - {"users", "accounts", "account_transactions", "term_agreements", "favorite_recipients"}:
            assert db.scalar(select(func.count()).select_from(Base.metadata.tables[name])) == 0
        assert all(verify_secret(u.password_hash, "Test1234!") and verify_secret(u.pin, "493827") for u, _ in accounts)
        for user, account in accounts:
            print(f"{user.user_name}: {user.email} / {account.account_num} / {account.balance:,} KRW")
    print("Committed: exactly two test users; old user records removed; products and terms preserved.")


if __name__ == "__main__":
    main()
