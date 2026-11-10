"""Flash-Lite 조회에서 서버가 확정할 수 있는 기간과 후속 질문."""

import re
from datetime import date, timedelta


MONTH = re.compile(r"(지난|이번)\s*달")
PARTIAL_OR_ABSOLUTE = re.compile(
    r"\d{4}\s*년|\d{4}[-./]\d|\d{1,2}\s*월|(?<!\d)(?!1\s*일부터)\d+\s*일|"
    r"첫날|마지막\s*날|초순|중순|하순|(?:지난|이번)\s*달\s*(?:초|중순|말(?!일까지))|"
    r"주차|\d+\s*주|(?:첫|둘째|셋째|넷째|다섯째|마지막)\s*주|보름"
)
PERIOD_ONLY = re.compile(r"(?:그럼\s*)?(?:지난|이번)\s*달(?:은|도)?[?？.!\s]*")
CATEGORY_ONLY = re.compile(
    r"같은\s*기간\s*(?:이번엔\s*)?(카페|식비|쇼핑|교통|편의점|기타)(?:은|는|도)?[?？.!\s]*"
    r"(?:내역이\s*없(?:다면|으면)\s*없다고\s*알려\s*줘[.!\s]*)?"
)
BALANCE_QUESTION = re.compile(
    r"(?:잔액(?:만|이|은)?\s*(?:얼마(?:야|예요)?|알려\s*줘|보여\s*줘)|"
    r"(?:지금\s*)?(?:남은\s*돈이\s*얼마(?:야|예요)?|얼마\s*남았(?:어|어요)))"
    r"[?？.!\s]*"
)


def month_ranges(today: date) -> dict[str, tuple[str, str]]:
    first = today.replace(day=1)
    last = first - timedelta(days=1)
    return {
        "지난": (last.replace(day=1).isoformat(), last.isoformat()),
        "이번": (first.isoformat(), today.isoformat()),
    }


def requested_range(message: str, ranges: dict, previous_card: dict | None) -> tuple[str, str] | None:
    if PARTIAL_OR_ABSOLUTE.search(message):
        return None
    months = set(MONTH.findall(message))
    if len(months) == 1:
        month = next(iter(months))
        if month == "지난" and "오늘" in message:
            return None
        return ranges[month]
    if not months and previous_card and re.search(r"같은\s*기간", message):
        return previous_card["start"], previous_card["end"]
    return None


def literal_account_hint(message: str, hint: str, labels: list[str]) -> str:
    hits = {label for label in labels if label and re.search(rf"(?<!\w){re.escape(label)}", message)}
    if len(hits) == 1:
        label = next(iter(hits))
        if not hint or hint not in message or label in hint or label.startswith(hint):
            return label
    return hint


def simple_balance_question(message: str, label: str | None) -> bool:
    subject = re.escape(label) if label else r"(?:계좌|통장)"
    subject_prefix = rf"(?:내\s+)?{subject}(?:에|의)?\s*"
    return bool(re.fullmatch(subject_prefix + BALANCE_QUESTION.pattern, message.strip()))


def card_followup_args(message: str, period: tuple[str, str] | None, previous: dict | None) -> dict | None:
    if not previous or not period:
        return None
    args = {**previous, "start": period[0], "end": period[1]}
    category = CATEGORY_ONLY.fullmatch(message.strip())
    if category:
        return {**args, "category": category[1]}
    if PERIOD_ONLY.fullmatch(message.strip()):
        return args
    return None
