"""에이전트가 쓰는 데이터 접근 (docs/agent-design.md §4, §7).

- user_id 는 make_tools()의 클로저로만 들어온다. LLM 도구 인자에는 없다 → 남의 계좌를 고를 방법이 없다.
- 내부는 백엔드 서비스 함수(app.services.*)를 그대로 호출해 소유자 검사를 재사용한다.
- LLM에 가는 값은 마스킹: 계좌번호 110-****-5678, 상대방 이름 홍*동.
- 받는 분·계좌·카드 매칭은 LLM이 아니라 여기 코드가 한다 (프롬프트 인젝션으로 대상을 바꿀 수 없게).
"""

import re
import uuid
from datetime import date, datetime, time

from langchain_core.tools import tool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import KST, Account, AccountProduct, AccountTransaction, Card, CardPayment, FavoriteRecipient, User
from app.services import accounts as acc_svc


def mask_num(num: str) -> str:
    return f"{num[:4]}****{num[8:]}"


def mask_name(name: str | None) -> str:
    return acc_svc.mask_name(name) if name else "-"


def account_label(db: Session, a: Account) -> str:
    return a.nickname or db.get(AccountProduct, a.product_id).product_name


def my_accounts(db: Session, user_id: uuid.UUID) -> list[Account]:
    return list(db.scalars(select(Account).where(Account.user_id == user_id, Account.status != "CLOSED")
                           .order_by(Account.is_favorite.desc(), Account.created_at, Account.id)))


def match_accounts(db: Session, user_id: uuid.UUID, hint: str | None) -> list[Account]:
    """'월급통장', '파킹', '5678' 같은 힌트로 내 계좌 고르기. 힌트가 없으면 전부."""
    accs = my_accounts(db, user_id)
    if not hint:
        return accs
    h = re.sub(r"\s", "", hint)
    hit = [a for a in accs if h in re.sub(r"\s", "", account_label(db, a)) or h in a.account_num.replace("-", "")]
    if not hit:  # "입출금통장에서" → "입출금"처럼 조사·통장을 떼고 한 번 더
        core = re.sub(r"(통장|계좌|에서|으로|로)$", "", re.sub(r"(에서|으로|로)$", "", h))
        hit = [a for a in accs if core and core in re.sub(r"\s", "", account_label(db, a))]
    return hit


def find_recipients(db: Session, user_id: uuid.UUID, who: str) -> list[dict]:
    """받는 분 후보. 계좌번호면 그 계좌, 아니면 즐겨찾기(별칭·예금주) → 최근 보낸 상대 이름 순.
    반환: [{account_id, account_num, holder_name, alias}] — 2명 이상이거나 0명이면 호출자가 되묻는다."""
    digits = re.sub(r"\D", "", who)
    if len(digits) >= 10:
        acc = db.scalar(select(Account).where(func.replace(Account.account_num, "-", "") == digits, Account.status != "CLOSED"))
        if acc is None:
            return []
        return [{"account_id": acc.id, "account_num": acc.account_num, "holder_name": db.get(User, acc.user_id).user_name, "alias": None}]
    w = who.strip()
    if re.search(r"통장|계좌", w):  # "생활비통장으로" = 내 계좌끼리 이체
        me = db.get(User, user_id).user_name
        own = match_accounts(db, user_id, w)
        if own:
            return [{"account_id": a.id, "account_num": a.account_num, "holder_name": me, "alias": account_label(db, a)} for a in own]
    favs =db.scalars(select(FavoriteRecipient).where(FavoriteRecipient.user_id == user_id)).all()
    hits = [f for f in favs if w in (f.alias or "") or w == f.holder_name or (len(w) >= 2 and w in f.holder_name)]
    out, seen = [], set()
    for f in hits:
        acc = db.scalar(select(Account).where(Account.account_num == f.account_num, Account.status != "CLOSED"))
        if acc and acc.id not in seen:
            seen.add(acc.id)
            out.append({"account_id": acc.id, "account_num": acc.account_num, "holder_name": f.holder_name, "alias": f.alias})
    if out:
        return out
    # 최근 1년 내 보낸 상대 중 이름이 같은 사람
    mine = [a.id for a in my_accounts(db, user_id)]
    rows = db.execute(select(AccountTransaction.counterparty_name, AccountTransaction.counterparty_account)
                      .where(AccountTransaction.account_id.in_(mine), AccountTransaction.transaction_direction == "OUT",
                             AccountTransaction.counterparty_name == w).distinct()).all()
    for name, num in rows:
        acc = db.scalar(select(Account).where(Account.account_num == num, Account.status != "CLOSED"))
        if acc and acc.id not in seen and acc.user_id != user_id:
            seen.add(acc.id)
            out.append({"account_id": acc.id, "account_num": num, "holder_name": name, "alias": None})
    return out


def my_cards(db: Session, user_id: uuid.UUID) -> list[Card]:
    return list(db.scalars(select(Card).join(Account, Card.account_id == Account.id)
                           .where(Account.user_id == user_id, Card.status.in_(("ACTIVE", "SUSPENDED")))))


def card_label(c: Card) -> str:
    return f"체크카드(끝자리 {c.card_number[-4:]})"


def set_card_status(db: Session, user_id: uuid.UUID, card_id: uuid.UUID, status: str) -> Card:
    # ponytail: 카드 서비스(app/services/cards.py)가 아직 없어 여기서 상태만 바꾼다. 서비스가 생기면 그 함수로 교체
    card = db.scalar(select(Card).join(Account, Card.account_id == Account.id).where(Card.id == card_id, Account.user_id == user_id))
    if card is None:
        raise BankError("INVALID_CARD", "카드를 찾을 수 없어요.", 404)
    card.status = status
    db.commit()
    return card


def _period(start: str | None, end: str | None) -> tuple[date | None, date | None]:
    return (date.fromisoformat(start) if start else None, date.fromisoformat(end) if end else None)


def make_tools(db: Session, user_id: uuid.UUID):
    """읽기 전용 도구. user_id 는 클로저로 고정."""

    def resolve(account: str | None) -> list[Account]:
        accs = match_accounts(db, user_id, None if not account or account in ("전체", "all") else account)
        if not accs:
            raise BankError("INVALID_FROM", f"'{account}'에 맞는 계좌가 없어요.")
        return accs

    @tool
    def list_accounts() -> list[dict]:
        """내 계좌 목록과 잔액, 상태(정상/거래중지)를 조회한다."""
        return [{"계좌": account_label(db, a), "계좌번호": mask_num(a.account_num), "잔액": a.balance,
                 "상태": {"ACTIVE": "정상", "SUSPENDED": "거래중지"}.get(a.status, a.status)} for a in my_accounts(db, user_id)]

    @tool
    def get_transactions(account: str = "전체", start: str | None = None, end: str | None = None,
                         direction: str = "ALL", keyword: str | None = None) -> str:
        """계좌 거래내역을 Markdown 표로 조회한다.
        account: 계좌 이름 일부(예: '입출금', '파킹') 또는 '전체'. start/end: YYYY-MM-DD (없으면 최근 3개월).
        direction: IN(입금)/OUT(출금)/ALL. keyword: 상대방 이름이나 메모에 들어간 단어."""
        s, e = _period(start, end)
        lines = ["| 날짜 | 계좌 | 구분 | 금액 | 상대 | 메모 |", "|---|---|---|---|---|---|"]
        rows = []
        for a in resolve(account):
            for t in acc_svc.list_transactions(db, user_id, a.id, start=s, end=e, direction=direction, q=keyword):
                rows.append((t["transaction_at"], account_label(db, a), t))
        for at, label, t in sorted(rows, key=lambda r: r[0], reverse=True)[:30]:
            lines.append(f"| {at:%Y-%m-%d %H:%M} | {label} | {'입금' if t['transaction_direction'] == 'IN' else '출금'} | {t['amount']:,} "
                         f"| {mask_name(t['counterparty_name'])} | {t['memo'] or ''} |")
        return "\n".join(lines) + f"\n(총 {len(rows)}건{', 최근 30건만 표시' if len(rows) > 30 else ''})"

    @tool
    def get_limits(account: str) -> list[dict]:
        """계좌의 1일·1달 이체한도와 오늘·이번 달 사용액을 조회한다. account: 계좌 이름 일부."""
        return [{"계좌": account_label(db, a), "1일한도": a.daily_limit, "1달한도": a.month_limit, **acc_svc.account_usage(db, a)}
                for a in resolve(account)]

    @tool
    def card_spending(start: str, end: str, category: str | None = None) -> dict:
        """체크카드 결제 합계와 카테고리별 금액, 최근 결제 5건. start/end: YYYY-MM-DD (end 포함).
        category: 카페·식비·쇼핑·교통·편의점 등 (없으면 전체)."""
        cards = [c.id for c in db.scalars(select(Card).join(Account, Card.account_id == Account.id).where(Account.user_id == user_id))]
        q = select(CardPayment).where(CardPayment.card_id.in_(cards),
                                      CardPayment.request_at >= datetime.combine(date.fromisoformat(start), time.min, KST),
                                      CardPayment.request_at <= datetime.combine(date.fromisoformat(end), time.max, KST))
        if category:
            q = q.where(CardPayment.category == category)
        pays = db.scalars(q.order_by(CardPayment.request_at.desc())).all()
        by_cat: dict[str, int] = {}
        for p in pays:
            by_cat[p.category or "기타"] = by_cat.get(p.category or "기타", 0) + p.amount
        return {"합계": sum(p.amount for p in pays), "건수": len(pays), "카테고리별": by_cat,
                "최근": [{"날짜": f"{p.request_at:%m-%d}", "가맹점": p.place, "금액": p.amount} for p in pays[:5]]}

    return [list_accounts, get_transactions, get_limits, card_spending]
