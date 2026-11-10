"""가상 입출금 상품의 읽기 전용 비교. 패턴 집계·후보 순서는 코드, 설명은 에이전트가 맡는다."""
import json
import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select

from app.errors import BankError
from app.models import KST, AccountProduct, User, now_kst
from app.services import insights
from app.services.verification import aware


@lru_cache(maxsize=1)
def product_catalog():
    # 프론트 상품 상세와 같은 공개 원본. Docker 이미지에도 이 파일만 복사한다.
    path = Path(__file__).resolve().parents[3] / "data" / "products.json"
    return {row["id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}


def recommend_accounts(db, user_id, purpose="general", *, at=None, pair_only=False):
    if purpose not in ("general", "spending", "savings", "group"):
        raise BankError("INVALID_INPUT", "통장 사용 목적을 확인해 주세요.")
    user = db.get(User, user_id)
    if user is None or user.status != "ACTIVE":
        raise BankError("AUTH", "로그인한 회원의 정보가 필요해요.", 401)
    at = aware(at or now_kst()).astimezone(KST)
    today = at.date()
    start = today - timedelta(days=90)
    cutoff = datetime.combine(today, time.min, KST) - timedelta(microseconds=1)
    accounts, rows = insights.history(db, user_id, start, cutoff)
    forecast = insights.balance_forecast(db, user_id, at=at)
    enough = forecast["상태"] == "예측완료"
    outgoing = [(t, p) for t, p in rows if t.transaction_direction == "OUT"]
    card_total = sum(t.amount for t, p in outgoing if p or t.transaction_type == "CARD")
    by_category = defaultdict(int)
    for t, payment in outgoing:
        if payment or t.transaction_type == "CARD":
            by_category[insights.category(t, payment)] += t.amount
    recurring = insights.subscription_candidates(rows, today)
    previous = insights.month_start(today, -1)
    salary = sum(t.amount for t, _ in rows if t.transaction_direction == "IN" and t.amount >= 500_000
                 and previous <= aware(t.transaction_at).astimezone(KST).date() < insights.month_start(today)
                 and re.search(r"급여|상여", f"{t.counterparty_name or ''} {t.memo or ''}"))
    age = None
    if user.birth and user.birth <= today:
        age = today.year - user.birth.year - ((today.month, today.day) < (user.birth.month, user.birth.day))
    profile = {"시작일": str(start), "종료일": str(cutoff.date()), "관측일수": forecast["관측일수"],
               "출금건수": len(outgoing), "카드소비": card_total,
               "주요소비": [{"분류": label, "금액": amount} for label, amount in sorted(by_category.items(), key=lambda row: (-row[1], row[0]))[:3]],
               "정기결제후보수": len(recurring), "전월급여성입금": salary,
               "현재총잔액": forecast["현재총잔액"], "월말예상잔액": forecast.get("월말예상잔액"),
               "예상부족액": forecast.get("예상부족액")}
    notes = ["가상 상품의 비교 안내이며 자동 개설이나 가입 자격 확정이 아니에요.",
             "카페·쇼핑 지출이 많아도 해당 업종 할인 혜택이 생기는 것은 아니에요.",
             "급여성 입금은 문구·금액으로 찾은 후보이며 우대금리 적용 실적을 보장하지 않아요.",
             "잔액 예측은 미래 입금 0원 가정이에요. 계좌이체는 소비와 별도로 보고 내 계좌 이체는 제외했어요."]
    if age is None:
        notes.append("생년월일이 확인되지 않아 청년 통장은 자동 맞춤 후보에서 제외했어요.")
    result = {"상태": "소비패턴기준비교" if enough else "목적기준안내", "목적": purpose,
              "분석": profile, "추천": [], "주의": notes, "추가질문": None}
    if not enough:
        notes.append("28일·출금 5건 미만이라 소비패턴 맞춤 추천을 확정하지 않아요.")
        if purpose == "general":
            return result | {"상태": "데이터부족", "추가질문": "생활비 관리, 잠시 돈 보관, 모임 회비 중 어떤 목적으로 쓸 통장인가요?"}

    database_products = list(db.scalars(select(AccountProduct).order_by(AccountProduct.code)))
    held = {a.product_id for a in accounts if a.status != "CLOSED"}
    candidates = []
    desired = "basic" if pair_only and purpose == "spending" else {
        "spending": "living", "savings": "parking", "group": "group",
    }.get(purpose)
    for product in database_products:
        if pair_only and product.code not in ("basic", "parking"):
            continue
        spec = product_catalog().get(product.code)
        if not spec or product.interest_rate is None or product.interest_rate != Decimal(str(spec["rate"])):
            notes.append(f"{product.product_name}은 상품 상세와 현재 금리 조건을 확인한 뒤 비교할 수 있어요.")
            continue
        score, reasons = 0, []
        code = product.code
        if code == "basic":
            score = 15
            reasons.append("특정 우대 조건보다 일상 입출금의 기본 용도로 비교할 수 있어요.")
        elif code == "living":
            score = 10
            if enough and card_total:
                score += 35 if card_total * 2 >= sum(t.amount for t, _ in outgoing) else 15
                reasons.append(f"분석 기간 카드 소비가 {card_total:,}원이어서 생활비 분리 관리 용도로 비교해요.")
            if enough and recurring:
                score += 15
                reasons.append(f"월 정기결제 후보가 {len(recurring)}개 있어 고정 지출을 모아 관리할 수 있어요.")
            if enough and forecast["예상부족액"] > 0:
                score += 35
                reasons.append(f"미래 입금 0원 가정의 월말 부족 추정액 {forecast['예상부족액']:,}원이 있어 생활비 계획을 우선 비교해요.")
            if enough and salary:
                score += 25
                reasons.append(f"전월 급여성 입금 {salary:,}원이 관측됐어요. 실제 급여 우대 인정 여부는 별도 확인해야 해요.")
        elif code == "parking":
            if not pair_only and purpose != "savings" and (not enough or forecast["월말예상잔액"] <= 0):
                continue
            score = 20
            if enough and forecast["월말예상잔액"] > 0:
                score += 20 if forecast["월말예상잔액"] * 2 >= forecast["현재총잔액"] else 0
                reasons.append(f"예측상 월말 잔액 {forecast['월말예상잔액']:,}원이 있어 수시로 꺼낼 대기 자금 보관 용도로 비교해요.")
            else:
                reasons.append("수시로 꺼낼 자금을 잠시 보관할 때 비교할 수 있어요.")
        elif code == "youth":
            if age is None or not 19 <= age <= 34:
                continue
            score = 22
            reasons.append("기록된 생년월일은 청년 상품의 연령 범위에 해당해요. 금액 구간과 가입 조건도 확인해야 해요.")
        elif code == "group":
            if purpose != "group":
                continue
            score = 20
            reasons.append("직접 말씀하신 모임 회비 관리 목적을 기준으로 비교해요. 이체 상대만 보고 모임이라고 추정하지 않았어요.")
        else:
            continue
        if code == desired:
            score += 200
            reasons.insert(0, "말씀하신 통장 사용 목적을 우선 반영했어요.")
        if not pair_only and not enough and code not in (desired, "basic"):
            continue
        already_held = product.id in held
        if already_held:
            reasons.append("이미 보유한 상품이에요. 새로 가입하기보다 기존 통장 활용을 먼저 비교해 보세요.")
        candidates.append({"code": code, "name": product.product_name, "score": score, "owned": already_held,
                           "reasons": reasons, "maxRate": spec["rate"], "baseRate": spec["baseRate"],
                           "conditions": spec["conditions"], "rateTable": spec["rateTable"], "notices": spec["notices"]})
    result["추천"] = sorted(candidates, key=lambda row: (-row["score"], row["code"]))[:3]
    if not candidates:
        result["상태"] = "상품조건확인필요"
    return result
