"""기존 data/golden_set.csv에서 문항을 골라 PDF 원문과 대조·검수한 골든셋(golden/golden_eval.csv)을 만든다.

실행(이 폴더에서): python golden.py
- paragraph·text 문항만 후보 (table·image는 텍스트 추출로 답할 수 없어 제외)
- 후보 페이지의 원문으로 LLM이 근거 구절(evidence)을 원문 그대로 발췌 → 원문에 실제로 있는지 문자열로 재확인
- 통과한 문항만 도메인당 PER_DOMAIN개까지 저장, 탈락 사유는 rejected.csv에 남긴다.
골든셋은 data/ 밖에 둔다 (검색 DB에 들어가면 안 된다).
"""

import csv
import random
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field

from ingest import DATA_DIR, load_pdf

SOURCE = DATA_DIR / "golden_set.csv"
OUT_DIR = Path(__file__).parent / "golden"
PER_DOMAIN = 8
SEED = 42
FIELDS = ["domain", "question", "target_answer", "evidence", "target_file_name", "target_page_no", "context_type"]

llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", temperature=0)


class Check(BaseModel):
    supported: bool = Field(description="기준 답변의 핵심 내용이 페이지 원문으로 뒷받침되면 true")
    evidence: str = Field(description="답변을 뒷받침하는 원문 구절. 페이지 원문에서 한 글자도 바꾸지 말고 그대로 복사한 1~2문장. 없으면 빈 문자열")


checker = llm.with_structured_output(Check)


def squash(text):
    return "".join(text.split())  # 줄바꿈·공백 차이를 무시하고 비교


@lru_cache(maxsize=8)
def pdf_pages(domain, file_name):
    return {d.metadata["page_no"]: d.page_content for d in load_pdf(DATA_DIR / domain / file_name)}


def verify(row):
    """(통과 여부, evidence 또는 탈락 사유)"""
    page = pdf_pages(row["domain"], row["target_file_name"]).get(int(row["target_page_no"]))
    if not page:
        return False, "해당 페이지 텍스트 없음"
    result = checker.invoke(
        f"""질문과 기준 답변이 아래 페이지 원문으로 뒷받침되는지 검수하라.

질문: {row['question']}
기준 답변: {row['target_answer']}

페이지 원문:
{page}"""
    )
    if not result.supported:
        return False, "원문이 답을 뒷받침하지 않음"
    if squash(result.evidence) not in squash(page):
        return False, "근거 구절이 원문에 없음"
    return True, result.evidence.strip()


def main():
    rows = [
        r for r in csv.DictReader(SOURCE.open(encoding="utf8"))
        if r["context_type"] in ("paragraph", "text") and r["target_page_no"].strip().isdigit()
    ]
    random.Random(SEED).shuffle(rows)
    by_domain = defaultdict(list)
    for r in rows:
        by_domain[r["domain"]].append(r)

    kept, rejected = [], []
    for domain, candidates in sorted(by_domain.items()):
        candidates.sort(key=lambda r: r["target_file_name"])  # 같은 파일끼리 묶어 PDF를 한 번만 읽는다
        random.Random(SEED).shuffle(candidates)
        n = 0
        for r in candidates:
            if n == PER_DOMAIN:
                break
            ok, info = verify(r)
            print(f"{domain} {'OK ' if ok else 'REJ'} {r['target_file_name'][:20]} p{r['target_page_no']} {'' if ok else info}")
            if ok:
                kept.append({**r, "evidence": info})
                n += 1
            else:
                rejected.append({**r, "evidence": info})

    OUT_DIR.mkdir(exist_ok=True)
    for name, data in [("golden_eval.csv", kept), ("rejected.csv", rejected)]:
        with (OUT_DIR / name).open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: 엑셀에서 한글이 안 깨진다
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)
    print(f"통과 {len(kept)}문항, 탈락 {len(rejected)}문항 → {OUT_DIR}")


if __name__ == "__main__":
    main()
