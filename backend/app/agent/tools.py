"""에이전트가 쓰는 데이터 접근 (docs/agent-design.md §4, §7).

- user_id 는 make_tools()의 클로저로만 들어온다. LLM 도구 인자에는 없다 → 남의 계좌를 고를 방법이 없다.
- 내부는 백엔드 서비스 함수(app.services.*)를 그대로 호출해 소유자 검사를 재사용한다.
- LLM에 가는 값은 마스킹: 계좌번호 110-****-5678, 상대방 이름 홍*동.
- 받는 분·계좌·카드 매칭은 LLM이 아니라 여기 코드가 한다 (프롬프트 인젝션으로 대상을 바꿀 수 없게).
"""

import re
import uuid
from typing import Literal
from datetime import date, datetime, time

from langchain_core.tools import tool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import KST, Account, AccountProduct, AccountTransaction, Card, CardPayment, FavoriteRecipient, User, now_kst
from app.services import accounts as acc_svc
from app.services import cards as card_svc
from app.services import insights
from app.services import recommendations
from app.services.transfers import find_recipient, list_favorites, recent_recipients, recipient_visible


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
    number_hint = h.replace("-", "")
    hit = [a for a in accs if h in re.sub(r"\s", "", account_label(db, a))
           or (number_hint.isdecimal() and number_hint in a.account_num.replace("-", ""))]
    if not hit:  # "입출금통장에서" → "입출금"처럼 조사·통장을 떼고 한 번 더
        core = re.sub(r"(통장|계좌|에서|으로|로)$", "", re.sub(r"(에서|으로|로)$", "", h))
        hit = [a for a in accs if core and core in re.sub(r"\s", "", account_label(db, a))]
    return hit


def recipient_choice(label: str, account_num: str) -> dict:
    return {"label": f"{label} · {mask_num(account_num)}", "value": account_num}


def recipient_choices(db: Session, user_id: uuid.UUID) -> list[dict]:
    own = [recipient_choice(account_label(db, a), a.account_num) for a in my_accounts(db, user_id) if a.status == "ACTIVE"]
    own_numbers = {item["value"] for item in own}
    blocks = []
    for title, rows in (("즐겨찾기", list_favorites(db, user_id)), ("최근 송금한 사람", recent_recipients(db, user_id))):
        seen = own_numbers.copy()
        options = []
        for row in rows:
            number = row["account_num"]
            if number in seen:
                continue
            try:
                find_recipient(db, number, user_id)
            except BankError:
                continue
            seen.add(number)
            options.append(recipient_choice(row.get("alias") or row["holder_name"], number))
            if len(options) == 3:
                break
        if options:
            blocks.append({"kind": "choices", "title": title, "options": options})
    if len(own) > 1:
        blocks.append({"kind": "choices", "title": "내 계좌", "options": own})
    return [*blocks, {"kind": "choices", "options": [{"label": "계좌번호 직접 입력"}]}]


def find_recipients(db: Session, user_id: uuid.UUID, who: str) -> list[dict]:
    """받는 분 후보. 계좌번호, 내 계좌 이름, 즐겨찾기 별칭·예금주와 최근 송금 이름을 확인한다.
    반환: [{account_id, account_num, holder_name, alias}] — 2명 이상이거나 0명이면 호출자가 되묻는다."""
    digits = re.sub(r"\D", "", who)
    if len(digits) == 11:
        try:
            acc = find_recipient(db, f"{digits[:3]}-{digits[3:7]}-{digits[7:]}", user_id)
        except BankError:
            return []
        return [{"account_id": acc.id, "account_num": acc.account_num, "holder_name": db.get(User, acc.user_id).user_name,
                 "alias": account_label(db, acc) if acc.user_id == user_id else None}]
    w = who.strip()
    if re.search(r"통장|계좌", w):  # "생활비통장으로" = 내 계좌끼리 이체
        me = db.get(User, user_id).user_name
        own = [a for a in match_accounts(db, user_id, w) if a.status == "ACTIVE"]
        if own:
            return [{"account_id": a.id, "account_num": a.account_num, "holder_name": me, "alias": account_label(db, a)} for a in own]
    favs = db.scalars(select(FavoriteRecipient).where(FavoriteRecipient.user_id == user_id)).all()
    hits = [f for f in favs if w in (f.alias or "") or w == f.holder_name or (len(w) >= 2 and w in f.holder_name)]
    out, seen = [], set()
    for f in hits:
        acc = db.scalar(select(Account).where(Account.account_num == f.account_num, Account.status == "ACTIVE"))
        if acc and acc.id not in seen and recipient_visible(db, user_id, acc.user_id):
            seen.add(acc.id)
            out.append({"account_id": acc.id, "account_num": acc.account_num, "holder_name": f.holder_name, "alias": f.alias})
    # 보낸 상대 중 이름이 같은 계좌도 확인해 즐겨찾기의 동명이인과 구분한다.
    mine = [a.id for a in my_accounts(db, user_id)]
    rows = db.execute(select(AccountTransaction.counterparty_name, AccountTransaction.counterparty_account)
                      .where(AccountTransaction.account_id.in_(mine), AccountTransaction.transaction_direction == "OUT",
                             AccountTransaction.counterparty_name == w).distinct()).all()
    for name, num in rows:
        acc = db.scalar(select(Account).where(Account.account_num == num, Account.status == "ACTIVE"))
        if acc and acc.id not in seen and acc.user_id != user_id and recipient_visible(db, user_id, acc.user_id):
            seen.add(acc.id)
            out.append({"account_id": acc.id, "account_num": num, "holder_name": name, "alias": None})
    return out


def sent_transfers(user_id: uuid.UUID):
    t = AccountTransaction
    return (select(t).join(Account, t.account_id == Account.id)
            .where(Account.user_id == user_id, t.transaction_direction == "OUT",
                   t.transaction_type.in_(("TRANSFER", "AUTO_TRANSFER")), t.amount > 0))


def sent_recipient_choices(db: Session, user_id: uuid.UUID, who: str) -> dict[str, str]:
    t = AccountTransaction
    choices = {c["account_num"]: c["alias"] or mask_name(c["holder_name"])
               for c in find_recipients(db, user_id, who)}
    sent = sent_transfers(user_id).with_only_columns(t.counterparty_account, t.counterparty_name).distinct()
    for number, name in db.execute(sent.where(t.counterparty_name == who, t.counterparty_account.is_not(None))):
        choices.setdefault(number, mask_name(name))
    return choices


def sent_transfer_amount(db: Session, user_id: uuid.UUID, recipient_number: str, *, monthly=False):
    t = AccountTransaction
    sent = sent_transfers(user_id).where(t.counterparty_account == recipient_number)
    if not monthly:
        return db.scalar(sent.with_only_columns(t.amount).order_by(t.transaction_at.desc(), t.id.desc()).limit(1))
    now = now_kst()
    start = datetime.combine(now.date().replace(day=1), time.min, KST)
    return db.execute(sent.where(t.transaction_at >= start, t.transaction_at <= now)
                      .with_only_columns(func.count(t.id), func.coalesce(func.sum(t.amount), 0))).one()


def my_cards(db: Session, user_id: uuid.UUID) -> list[Card]:
    return list(db.scalars(select(Card).join(Account, Card.account_id == Account.id)
                           .where(Account.user_id == user_id, Card.status.in_(("ACTIVE", "SUSPENDED")))))


def card_label(c: Card) -> str:
    return f"체크카드(끝자리 {card_svc.last4(c)})"


def set_card_status(db: Session, user_id: uuid.UUID, card_id: uuid.UUID, status: str) -> Card:
    return card_svc.set_card_status(db, user_id, card_id, status)


def _period(start: str | None, end: str | None) -> tuple[date | None, date | None]:
    return (date.fromisoformat(start) if start else None, date.fromisoformat(end) if end else None)


def make_tools(db: Session, user_id: uuid.UUID, *, account: Account | None = None):
    """읽기 전용 도구. user_id 는 클로저로 고정."""

    def resolve(hint: str | None) -> list[Account]:
        accs = match_accounts(db, user_id, None if not hint or hint in ("전체", "all") else hint)
        if account is not None:
            accs = [a for a in accs if a.id == account.id]
        if not accs:
            raise BankError("INVALID_FROM", "요청하신 계좌를 찾을 수 없어요.")
        return accs

    @tool
    def list_accounts() -> list[dict]:
        """내 계좌 목록과 잔액, 상태(정상/거래중지)를 조회한다."""
        accounts = my_accounts(db, user_id)
        if account is not None:
            accounts = [a for a in accounts if a.id == account.id]
        return [{"계좌": account_label(db, a), "계좌번호": mask_num(a.account_num), "잔액": a.balance,
                 "상태": {"ACTIVE": "정상", "SUSPENDED": "거래중지"}.get(a.status, a.status)} for a in accounts]

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

    @tool
    def spending_analysis(month: str | None = None) -> dict:
        """소비 패턴·카테고리별 지출·전월 대비 증감 원인을 코드로 계산한다.
        month: YYYY-MM. 없으면 이번 달. 이번 달은 전월 같은 일자까지 비교한다.
        카드 소비와 용도 미확정 이체를 분리하며 내 계좌 사이 이체는 제외한다."""
        return insights.spending_analysis(db, user_id, month)

    @tool
    def balance_forecast(month: str | None = None) -> dict:
        """이번 달 또는 다음 달 예상 지출·월말 잔액·부족액·하루 출금 예산을 코드로 계산한다.
        '돈이 부족할 것 같은데 왜/어떻게 하지', '다음달 얼마 쓸까'에 사용한다.
        month: YYYY-MM. 없으면 이번 달. 데이터부족이면 예측 금액을 만들지 않는다.
        미래 입금 0원 가정, 등록된 자동이체와 정기결제 후보를 반영한 시나리오이다."""
        return insights.balance_forecast(db, user_id, month)

    @tool
    def detect_subscriptions() -> dict:
        """최근 180일 카드 원장에서 3회 이상 반복된 월 정기결제·구독 후보를 코드로 찾는다.
        같은 가맹점·25~35일 간격·금액 차이 10% 이내. 실제 구독 확정이나 해지가 아니다."""
        return insights.detect_subscriptions(db, user_id)

    @tool
    def recommend_accounts(purpose: Literal["general", "spending", "savings", "group"] = "general", pair_only: bool = False) -> dict:
        """내 소비·급여성 입금·보유 상품으로 가상 입출금통장 비교 후보를 계산한다.
        purpose: 명시한 생활비 spending, 대기자금 savings, 모임 group, 미지정 general.
        가입 자격·우대 적용을 확정하거나 자동 개설하지 않는다."""
        return recommendations.recommend_accounts(db, user_id, purpose, pair_only=pair_only)

    return [list_accounts, get_transactions, get_limits, card_spending, spending_analysis, balance_forecast, detect_subscriptions, recommend_accounts]
