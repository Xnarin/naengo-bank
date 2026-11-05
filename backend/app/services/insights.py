"""읽기 전용 소비 분석. 모든 금액·예측·반복 패턴은 코드에서 계산한다."""
import calendar
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from statistics import median_low

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import BankError
from app.models import KST, Account, AccountTransaction, AutoTransfer, CardPayment, now_kst
from app.services.auto_transfers import next_run
from app.services.verification import aware


def month_start(day: date, offset=0) -> date:
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def month_end(day: date) -> date:
    return month_start(day, 1) - timedelta(days=1)


def parse_month(month: str | None, today: date) -> date:
    if month is None:
        return month_start(today)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise ValueError
        return date.fromisoformat(month + "-01")
    except ValueError:
        raise BankError("INVALID_TIME", "분석할 월은 YYYY-MM 형식으로 알려 주세요.")


def history(db: Session, user_id, start: date, at: datetime):
    accounts = list(db.scalars(select(Account).where(Account.user_id == user_id)))
    numbers = {a.account_num for a in accounts}
    rows = db.execute(select(AccountTransaction, CardPayment).outerjoin(
        CardPayment, AccountTransaction.card_payment_id == CardPayment.id).where(
        AccountTransaction.account_id.in_([a.id for a in accounts]),
        AccountTransaction.transaction_at >= datetime.combine(start, time.min, KST),
        AccountTransaction.transaction_at <= at).order_by(AccountTransaction.transaction_at, AccountTransaction.id)).all()
    # 카드 결제는 원장 한 건만 집계한다. 카드 결제 테이블의 금액을 다시 더하지 않는다.
    return accounts, [(t, p) for t, p in rows if not (
        t.transaction_type in ("TRANSFER", "AUTO_TRANSFER") and t.counterparty_account in numbers)]


def category(t, payment) -> str:
    if payment or t.transaction_type == "CARD":
        return (payment.category if payment else None) or "카드·기타"
    return "자동·예약이체" if t.transaction_type == "AUTO_TRANSFER" else "계좌이체·기타출금"


def spending_analysis(db: Session, user_id, month: str | None = None, *, at=None) -> dict:
    at = aware(at or now_kst()).astimezone(KST)
    today = at.date()
    start = parse_month(month, today)
    if start > month_start(today) or start < month_start(today, -11):
        raise BankError("INVALID_TIME", "소비 분석은 이번 달을 포함한 최근 12개월에서 선택해 주세요.")
    end = min(month_end(start), today)
    previous = month_start(start, -1)
    comparison_end = min(month_end(previous), previous.replace(day=min(end.day, month_end(previous).day))) if start == month_start(today) else month_end(previous)
    _, rows = history(db, user_id, previous, min(at, datetime.combine(end, time.max, KST)))
    current, baseline = defaultdict(int), defaultdict(int)
    count, inflow, transfers = 0, 0, 0
    for t, payment in rows:
        day = aware(t.transaction_at).astimezone(KST).date()
        if start <= day <= end:
            if t.transaction_direction == "IN":
                inflow += t.amount
            else:
                current[category(t, payment)] += t.amount
                count += 1
                if t.transaction_type != "CARD":
                    transfers += t.amount
        elif previous <= day <= comparison_end and t.transaction_direction == "OUT":
            baseline[category(t, payment)] += t.amount
    total, previous_total = sum(current.values()), sum(baseline.values())
    days = (end - start).days + 1
    return {
        "상태": "분석완료" if count else "출금내역없음", "시작일": str(start), "종료일": str(end),
        "전체출금": total, "카드소비": total - transfers, "용도미확정_이체등출금": transfers,
        "기록된입금": inflow, "출금건수": count, "하루평균출금": total // days,
        "비교기간": {"시작일": str(previous), "종료일": str(comparison_end), "출금": previous_total},
        "비교기간대비증감액": total - previous_total,
        "분류별": [{"분류": name, "금액": amount, "이전기간금액": baseline[name], "증감액": amount - baseline[name]}
                  for name, amount in sorted(((name, current.get(name, 0)) for name in current.keys() | baseline.keys()),
                                             key=lambda item: (-item[1], item[0]))],
        "주의": ["내 계좌 사이 이체는 제외했어요.", "계좌이체는 소비인지 저축인지 확정하지 않고 별도로 표시해요.",
                 "이번 달은 전월 같은 일자까지 비교해요. 비교기간 거래가 없으면 0원은 기록 없음도 뜻해요."],
    }


def merchant_key(payment) -> str:
    return re.sub(r"\s+", " ", payment.place or "").strip().casefold()


def subscription_candidates(rows, today: date) -> list[dict]:
    grouped = defaultdict(list)
    for t, p in rows:
        if t.transaction_direction == "OUT" and p and merchant_key(p):
            grouped[merchant_key(p)].append((aware(t.transaction_at).astimezone(KST).date(), p))
    result = []
    for key, charges in grouped.items():
        charges.sort(key=lambda row: row[0])
        dates = [day for day, _ in charges]
        amounts = [p.amount for _, p in charges]
        typical = median_low(amounts)
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        if (len(charges) < 3 or (today - dates[-1]).days > 40 or not all(25 <= gap <= 35 for gap in gaps)
                or any(abs(amount - typical) * 10 > typical for amount in amounts)):
            continue
        anchor = max(day.day for day in dates)
        result.append({"가맹점": charges[-1][1].place, "비교키": key, "월예상금액": typical,
                       "관측횟수": len(charges), "최근결제일": str(dates[-1]), "기준결제일": anchor,
                       "근거": "3회 이상, 25~35일 간격, 금액 차이 10% 이내인 정기결제 후보"})
    return sorted(result, key=lambda row: (-row["월예상금액"], row["비교키"]))


def detect_subscriptions(db: Session, user_id, *, at=None) -> dict:
    at = aware(at or now_kst()).astimezone(KST)
    start = at.date() - timedelta(days=179)
    _, rows = history(db, user_id, start, at)
    candidates = subscription_candidates(rows, at.date())
    return {"시작일": str(start), "종료일": str(at.date()), "후보": candidates,
            "월예상합계": sum(row["월예상금액"] for row in candidates),
            "주의": "카드 원장의 반복 결제를 찾은 후보예요. 실제 구독 여부·해지 여부는 가맹점에서 확인해야 해요. 3회 미만이거나 연간 구독은 탐지하지 않아요."}


def planned_transfers(db, accounts, at, end):
    ids = {a.id for a in accounts}
    result = []
    for row in db.scalars(select(AutoTransfer).where(AutoTransfer.from_account_id.in_(ids), AutoTransfer.status == "ACTIVE")):
        if row.to_account_id in ids or (row.end_date and row.end_date < at.date()):
            continue
        planned = aware(row.next_run_at).astimezone(KST)
        while planned.date() <= end:
            effective = max(planned, at)
            if row.end_date and effective.date() > row.end_date:
                break
            result.append({"날짜": str(effective.date()), "금액": row.amount, "종류": "등록된 자동·예약이체"})
            following = next_run(row.cycle, row.run_day, row.start_date, row.end_date, max(at, planned))
            if following is None:
                break
            planned = following
    return result


def ceil_div(amount: int, denominator: int) -> int:
    return (amount + denominator - 1) // denominator


def balance_forecast(db: Session, user_id, month: str | None = None, *, at=None) -> dict:
    at = aware(at or now_kst()).astimezone(KST)
    today = at.date()
    target = parse_month(month, today)
    if target not in (month_start(today), month_start(today, 1)):
        raise BankError("INVALID_TIME", "잔액 예측은 이번 달 또는 다음 달을 선택해 주세요.")
    end = month_end(target)
    accounts, rows = history(db, user_id, today - timedelta(days=179), at)
    balance = sum(a.balance for a in accounts if a.status != "CLOSED")
    subscriptions = subscription_candidates(rows, today)
    fixed = planned_transfers(db, accounts, at, end)
    for candidate in subscriptions:
        last = date.fromisoformat(candidate["최근결제일"])
        planned = month_start(last, 1)
        while planned <= end:
            day = planned.replace(day=min(candidate["기준결제일"], month_end(planned).day))
            if day >= today:
                fixed.append({"날짜": str(day), "금액": candidate["월예상금액"], "종류": "정기결제 후보", "가맹점": candidate["가맹점"]})
            planned = month_start(planned, 1)
    fixed.sort(key=lambda row: (row["날짜"], row["금액"]))
    # 완료된 전날까지 최대 90일. 카드와 원장을 이중 집계하지 않는다.
    first = min((aware(t.transaction_at).astimezone(KST).date() for t, _ in rows), default=today)
    observed_start = max(today - timedelta(days=90), first)
    observed_days = (today - observed_start).days
    observed = [(t, p) for t, p in rows if observed_start <= aware(t.transaction_at).astimezone(KST).date() < today
                and t.transaction_direction == "OUT"]
    known_merchants = {row["비교키"] for row in subscriptions}
    variable = sum(t.amount for t, p in observed if t.transaction_type != "AUTO_TRANSFER" and (not p or merchant_key(p) not in known_merchants))
    result = {"기준시각": at.isoformat(), "대상월": target.strftime("%Y-%m"), "현재총잔액": balance,
              "관측시작일": str(observed_start), "관측일수": observed_days, "관측출금건수": len(observed),
              "예정지출": fixed, "예정지출합계": sum(row["금액"] for row in fixed),
              "주의": ["과거 패턴이 계속된다고 가정한 추정이에요. 확정 잔액이 아니에요.",
                       "미래 입금은 0원으로 가정해요. 예정 월급이 들어오면 실제 잔액은 달라져요.",
                       "등록된 이체는 성공한다고 가정해요. 정기결제는 취소·변경될 수 있는 후보예요.",
                       "계좌이체는 소비와 구분되지 않는 출금도 포함해요. 범위는 변동지출 ±20% 시나리오이며 통계적 신뢰구간이 아니에요."]}
    if observed_days < 28 or len(observed) < 5:
        return result | {"상태": "데이터부족", "이유": "최소 28일과 출금 5건이 필요해요. 지금은 등록된 예정지출만 안내할 수 있어요."}
    remaining_days = (end - today).days
    target_days = remaining_days if target == month_start(today) else calendar.monthrange(target.year, target.month)[1]
    variable_future = ceil_div(variable * remaining_days, observed_days)
    target_variable = ceil_div(variable * target_days, observed_days)
    target_fixed = sum(row["금액"] for row in fixed if date.fromisoformat(row["날짜"]) >= target)
    total_future = variable_future + result["예정지출합계"]
    target_future = target_variable + target_fixed
    month_spent = sum(t.amount for t, _ in rows if t.transaction_direction == "OUT" and aware(t.transaction_at).astimezone(KST).date() >= target)
    projected = balance - total_future
    series = [{"날짜": str(today), "잔액": balance}]
    for offset in range(1, remaining_days + 1):
        day = today + timedelta(days=offset)
        due = sum(row["금액"] for row in fixed if date.fromisoformat(row["날짜"]) <= day)
        series.append({"날짜": str(day), "잔액": balance - ceil_div(variable * offset, observed_days) - due})
    if not remaining_days:
        series.append({"날짜": str(end), "잔액": projected})
    result.update({"상태": "예측완료", "관측변동출금": variable, "남은일수": remaining_days,
                   "잔액추이": series,
                   "예상미래입금": 0, "남은기간예상변동출금": variable_future,
                   "대상월예측일수": target_days, "대상월예상변동출금": target_variable,
                   "대상월예정지출": target_fixed, "대상월기록된출금": month_spent,
                   "남은기간예상출금": total_future, "대상월예상출금": target_future + month_spent,
                   "대상월전체출금범위": {"최소": month_spent + target_fixed + target_variable * 80 // 100,
                                  "최대": month_spent + target_fixed + ceil_div(target_variable * 120, 100)},
                   "월말예상잔액": projected, "예상부족액": max(0, -projected),
                   "잔액하한시나리오": balance - result["예정지출합계"] - ceil_div(variable_future * 120, 100),
                   "잔액상한시나리오": balance - result["예정지출합계"] - variable_future * 80 // 100,
                   "기록된예정지출후하루출금가능액": max(0, balance - result["예정지출합계"]) // max(1, remaining_days),
                   "이번달주요출금": spending_analysis(db, user_id, at=at)["분류별"]})
    return result
