import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import Account, AccountProduct, AccountTransaction, LoginHistory, Notification, Term, TermAgreement, User, now_kst
from app.security import MAX_FAILS, create_access_token, hash_secret, verify_pin, verify_secret
from app.services.accounts import new_account_num
from app.services import verification


def find_by_email(db: Session, email: str, *, lock: bool = False) -> User | None:
    query = select(User).where(func.lower(User.email) == email.lower())
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def list_terms(db: Session, category: str) -> list[Term]:
    return list(db.scalars(select(Term).where(Term.category == category).order_by(Term.id)))


def signup(db: Session, *, email: str, password: str, pin: str, user_name: str,
           phone_num: str | None, agreed_term_ids: list[int]) -> User:
    if find_by_email(db, email):
        raise BankError("DUPLICATE_EMAIL", "이미 가입된 이메일이에요.", 409)
    try:
        verified = verification.assert_verified(db, email, "SIGNUP")
        terms = list_terms(db, "SIGNUP")
        agreed = set(agreed_term_ids)
        if not terms or not {t.id for t in terms if t.required} <= agreed or not agreed <= {t.id for t in terms}:
            raise BankError("TERMS_REQUIRED", "필수 약관에 동의해 주세요.")
        product = db.scalar(select(AccountProduct).where(AccountProduct.code == "basic"))
        if product is None:
            raise BankError("INVALID_PRODUCT", "기본 통장 정보를 찾을 수 없어요.", 404)
        user = User(email=email.lower(), password_hash=hash_secret(password), pin=hash_secret(pin),
                    user_name=user_name, phone_num=phone_num)
        db.add(user)
        db.flush()
        db.add_all([TermAgreement(user_id=user.id, term_id=t.id, agreed=t.id in agreed) for t in terms])
        # 자동 개설 통장은 임의의 4자리 해시를 저장한다. 현재 다른 업무에서는 사용하지 않는다(D5).
        account = Account(user_id=user.id, product_id=product.id, account_num=new_account_num(db),
                          account_password=hash_secret(f"{secrets.randbelow(10_000):04}"), balance=1_000_000)
        db.add(account)
        db.flush()
        db.add(AccountTransaction(account_id=account.id, transaction_type="DEPOSIT", transaction_direction="IN",
                                  amount=1_000_000, new_balance=1_000_000, counterparty_name="내금고", memo="가입 축하 가상머니"))
        verification.consume(verified)
        db.commit()
        return user
    except IntegrityError:
        db.rollback()
        raise BankError("DUPLICATE_EMAIL", "이미 가입된 이메일 또는 휴대폰 번호예요.", 409)
    except Exception:
        db.rollback()
        raise


def login(db: Session, email: str, secret: str, *, use_pin: bool, ip: str | None, user_agent: str | None) -> dict:
    user = find_by_email(db, email, lock=True)
    if user is None or user.status == "WITHDRAWN":
        raise BankError("AUTH", "이메일 또는 비밀번호가 일치하지 않아요.", 401)
    if user.status == "LOCKED":
        db.add(LoginHistory(user_id=user.id, ip=ip, user_agent=user_agent, success=False))
        db.commit()
        raise BankError("USER_LOCKED", "잠긴 계정이에요. 비밀번호 재설정으로 풀어 주세요.", 403)
    ok = verify_secret(user.pin if use_pin else user.password_hash, secret)
    previous = db.scalar(select(LoginHistory).where(LoginHistory.user_id == user.id, LoginHistory.success.is_(True))
                         .order_by(LoginHistory.id.desc()).limit(1))
    db.add(LoginHistory(user_id=user.id, ip=ip, user_agent=user_agent, success=ok))
    if ok and previous and (previous.ip != ip or previous.user_agent != user_agent):
        db.add(Notification(user_id=user.id, type="SUSPICIOUS_LOGIN", message="이전과 다른 기기 또는 네트워크에서 로그인했어요."))
    if use_pin:
        verify_pin(db, user, secret)
    elif not ok:
        user.login_fail_count += 1
        locked = user.login_fail_count >= MAX_FAILS
        if locked:
            user.status = "LOCKED"
        db.commit()
        if locked:
            raise BankError("USER_LOCKED", "비밀번호를 5회 틀려 계정이 잠겼어요. 비밀번호 재설정으로 풀어 주세요.", 403)
        raise BankError("AUTH", "이메일 또는 비밀번호가 일치하지 않아요.", 401)
    else:
        user.login_fail_count = 0
        db.commit()
    return {"access_token": create_access_token(user.id), "token_type": "bearer"}


def reset_password(db: Session, email: str, code: str, new_password: str) -> None:
    user = find_by_email(db, email, lock=True)
    if user is None or user.status == "WITHDRAWN":
        raise BankError("CODE", "본인확인 정보를 확인해 주세요.")
    verified = verification.verify_code(db, email, "RESET_PW", code)
    user.password_hash = hash_secret(new_password)
    user.status = "ACTIVE"
    user.login_fail_count = user.pin_fail_count = 0
    verification.consume(verified)
    db.commit()


def update_profile(db: Session, user: User, changes: dict) -> User:
    for key, value in changes.items():
        setattr(user, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise BankError("DUPLICATE_EMAIL", "이미 가입된 휴대폰 번호예요.", 409)
    return user


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    user = find_by_email(db, user.email, lock=True)
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요.", 401)
    if not verify_secret(user.password_hash, current_password):
        raise BankError("AUTH", "지금 비밀번호가 맞지 않아요.", 401)
    if current_password == new_password:
        raise BankError("AUTH", "지금과 다른 비밀번호를 정해 주세요.")
    user.password_hash = hash_secret(new_password)
    user.login_fail_count = 0
    db.commit()


def change_pin(db: Session, user: User, current_pin: str, new_pin: str) -> None:
    verify_pin(db, user, current_pin)
    if current_pin == new_pin or len(set(new_pin)) == 1 or new_pin in "0123456789" or new_pin in "9876543210":
        raise BankError("PIN", "지금과 다른 비밀번호를 정해 주세요. 같은 숫자 반복이나 연속된 숫자는 쓸 수 없어요.")
    user = find_by_email(db, user.email, lock=True)
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요.", 401)
    user.pin = hash_secret(new_pin)
    db.commit()


def withdraw(db: Session, user: User, password: str | None = None, *, pin: str | None = None) -> None:
    if pin is not None:
        verify_pin(db, user, pin)
    user = find_by_email(db, user.email, lock=True)
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "사용할 수 없는 계정이에요.", 401)
    if pin is None and (password is None or not verify_secret(user.password_hash, password)):
        raise BankError("AUTH", "비밀번호가 맞지 않아요.", 401)
    if db.scalar(select(Account.id).where(Account.user_id == user.id, Account.status != "CLOSED").limit(1)):
        raise BankError("CLOSE_BLOCKED", "모든 계좌를 해지한 뒤 탈퇴할 수 있어요.")
    user.status, user.withdrawn_at = "WITHDRAWN", now_kst()
    db.commit()
