"""로더 점검용 골든셋(golden/loader_check.csv)을 만든다. 일회성 스크립트.
- ocr 문항: 스캔(이미지) 페이지에 정답이 있는 질문. OCR 없이 로드하면 못 찾는다. OCR 텍스트에서 질문을 생성하고 근거 구절이 OCR 텍스트에 있는지 확인한다.
- text 문항: 같은 파일의 일반 텍스트 페이지 질문. 원본 골든셋에서 고르고 golden.verify로 검수한다. 파일 전체가 빠짐없이 로드됐는지 본다.
"""
import csv
import json
import random

from pydantic import BaseModel, Field

import golden
from golden import DATA_DIR, SOURCE, llm, squash

FILES = {  # 파일: (도메인, 질문을 만들 OCR 페이지)
    "240319 알기쉬운 청년농신보 책자(최종본)★_배포용": ("public", [3, 9, 17, 25, 29]),
    "한-호주 퇴직연금 포럼_책자(최종)": ("finance", []),  # OCR 페이지가 모두 빈 쪽
    "130292099630937500_KIFVIP2013-10": ("finance", [55]),
    "133178946057443204_WP22-05": ("finance", [1]),
    "2024 달라지는 세금제도": ("law", [1]),
}
FIELDS = ["domain", "question", "target_answer", "evidence", "target_file_name", "target_page_no", "page_kind", "source"]


class QA(BaseModel):
    question: str = Field(description="이 페이지 내용만으로 답할 수 있는 질문 하나. 문서를 보지 않은 사람도 이해하게 쓰고 '이 페이지', '위 표' 같은 지시어는 쓰지 않는다")
    answer: str = Field(description="질문의 답. 1~2문장")
    evidence: str = Field(description="답을 뒷받침하는 구절. 페이지 원문에서 한 글자도 바꾸지 말고 그대로 복사한 1~2문장")


maker = llm.with_structured_output(QA)
rows = []

for stem, (domain, pages) in FILES.items():
    ocr = {int(i) + 1: t for i, t in json.load(open(f"ocr_cache/{stem}.json", encoding="utf8")).items()}
    for page in pages:
        qa = maker.invoke(f"아래는 PDF {page}쪽을 OCR한 텍스트다. 질문과 답과 근거 구절을 만들어라." + chr(10) * 2 + ocr[page])
        ok = squash(qa.evidence) in squash(ocr[page])
        print(f"ocr  {stem[:20]} p{page} {'OK' if ok else 'REJ(근거가 OCR 텍스트에 없음)'}")
        if ok:
            rows.append({"domain": domain, "question": qa.question, "target_answer": qa.answer, "evidence": qa.evidence.strip(),
                         "target_file_name": stem + ".pdf", "target_page_no": page, "page_kind": "ocr", "source": "generated"})

    candidates = [r for r in csv.DictReader(SOURCE.open(encoding="utf-8-sig"))
                  if r["target_file_name"] == stem + ".pdf" and r["context_type"] in ("paragraph", "text")
                  and r["target_page_no"].strip().isdigit() and int(r["target_page_no"]) not in ocr]
    random.Random(42).shuffle(candidates)
    kept = 0
    for r in candidates:
        if kept == 2:
            break
        ok, info = golden.verify(r)
        print(f"text {stem[:20]} p{r['target_page_no']} {'OK' if ok else 'REJ ' + info}")
        if ok:
            rows.append({"domain": domain, "question": r["question"], "target_answer": r["target_answer"], "evidence": info,
                         "target_file_name": r["target_file_name"], "target_page_no": r["target_page_no"], "page_kind": "text", "source": "원본 골든셋(검수)"})
            kept += 1

with open("golden/loader_check.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
print(len(rows), "문항 저장")
