"""계산 도구 결과를 화면용 블록으로 변환한다. LLM이 차트 값을 만들지 않는다."""


def insight_block(name: str, result, arguments: dict | None = None) -> dict | None:
    if not isinstance(result, dict):
        return None
    if name == "spending_analysis":
        return {"kind": "spendingInsight", "start": result["시작일"], "end": result["종료일"],
                "total": result["전체출금"], "cardTotal": result["카드소비"], "transferTotal": result["용도미확정_이체등출금"],
                "categories": [{"label": row["분류"], "amount": row["금액"], "previous": row["이전기간금액"]} for row in result["분류별"]],
                "comparison": {"total": result["비교기간"]["출금"], "delta": result["비교기간대비증감액"],
                               "start": result["비교기간"]["시작일"], "end": result["비교기간"]["종료일"]},
                "notes": result["주의"]}
    if name == "card_spending":
        args = arguments or {}
        return {"kind": "spendingInsight", "start": args.get("start", ""), "end": args.get("end", ""),
                "total": result["합계"], "cardTotal": result["합계"], "transferTotal": 0,
                "categories": [{"label": label, "amount": amount} for label, amount in sorted(result["카테고리별"].items(), key=lambda row: -row[1])],
                "notes": ["선택한 기간의 카드 결제만 포함해요."]}
    if name == "balance_forecast":
        block = {"kind": "forecastInsight", "month": result["대상월"], "asOf": result["기준시각"],
                 "balance": result["현재총잔액"], "sufficient": result["상태"] == "예측완료",
                 "observedDays": result["관측일수"], "observedCount": result["관측출금건수"],
                 "fixedTotal": result["예정지출합계"], "reason": result.get("이유"), "notes": result["주의"],
                 "scheduled": [{"date": row["날짜"], "amount": row["금액"], "label": row.get("가맹점", row["종류"])} for row in result["예정지출"]]}
        if block["sufficient"]:
            block.update(estimatedExpense=result["대상월예상출금"], projectedBalance=result["월말예상잔액"],
                         shortage=result["예상부족액"], dailyBudget=result["기록된예정지출후하루출금가능액"],
                         expenseRange={"min": result["대상월전체출금범위"]["최소"], "max": result["대상월전체출금범위"]["최대"]},
                         points=[{"date": row["날짜"], "balance": row["잔액"]} for row in result["잔액추이"]])
        return block
    if name == "detect_subscriptions":
        return {"kind": "subscriptionInsight", "start": result["시작일"], "end": result["종료일"],
                "total": result["월예상합계"], "note": result["주의"],
                "items": [{"name": row["가맹점"], "amount": row["월예상금액"], "count": row["관측횟수"],
                           "lastDate": row["최근결제일"], "billingDay": row["기준결제일"]} for row in result["후보"]]}
    return None
