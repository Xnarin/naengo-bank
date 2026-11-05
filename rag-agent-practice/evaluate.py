"""골든셋으로 검색·답변을 평가한다. 결과는 eval_results/에 캐시되어 재실행하면 이어서 진행된다.

골든셋 (dataset)
  verified     golden/golden_eval.csv. PDF 원문과 대조해 검수한 40문항 (근거 구절 포함)
  extra        data/golden_set.csv의 나머지 paragraph·text 문항. 검수하지 않았다 (라벨에 노이즈가 있을 수 있다)
  unanswerable golden/unanswerable.csv. 문서에 답이 없는 질문. 정답은 "답변 보류"

검색 지표 (정답 = 골든셋의 파일명+페이지, 청크는 페이지를 넘지 않는다)
  hit@1/3/5    상위 k개 안에 정답 페이지의 청크가 있는 질문 비율
  mrr          정답 페이지 청크의 첫 순위의 역수 평균 (상위 10개 기준)
  precision@5  상위 5개 중 정답 페이지 청크의 비율
  file_hit@5   상위 5개 안에 정답 파일의 청크가 있는 비율
  evidence_hit@5  상위 5개 청크가 근거 구절(evidence)의 일부를 실제로 담고 있는 비율 (verified만)
답변 지표
  accuracy       LLM 판정 correct 1 / partial 0.5 / wrong 0 의 평균 (보류는 0점)
  faithfulness   답변이 검색된 청크로 뒷받침되는 정도 yes 1 / partial 0.5 / no 0 (답변한 것만)
  token_f1       기준 답변과 형태소 토큰 F1 (LLM과 무관한 자동 지표)
  cite_ok        답변한 것 중 정답 파일명·페이지를 출처로 표시한 비율
  answered       보류하지 않은 비율
  refusal_rate   (unanswerable) 답변을 보류하거나 "모른다"고 한 비율. 높을수록 좋다
  avg_sec / p95_sec / avg_searches  응답 시간과 검색 횟수
"""

import csv
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Literal

import pandas as pd
from langchain_core.output_parsers import StrOutputParser
from pydantic import BaseModel, Field

import agent
import tools

BASE = Path(__file__).parent
VERIFIED_PATH = BASE / "golden" / "golden_eval.csv"
REJECTED_PATH = BASE / "golden" / "rejected.csv"
UNANSWERABLE_PATH = BASE / "golden" / "unanswerable.csv"
SOURCE_PATH = BASE / "data" / "golden_set.csv"
RESULT_DIR = BASE / "eval_results"
K = 5
RETRIEVE_K = 10  # 검색 평가는 10개를 가져와 k=1,3,5로 잘라 본다
WORKERS = 4
VERDICT_SCORE = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}
FAITH_SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0}


def read_csv(path):
    return list(csv.DictReader(path.open(encoding="utf-8-sig")))


def load_golden(dataset="verified"):
    if dataset == "verified":
        return read_csv(VERIFIED_PATH)
    if dataset == "unanswerable":
        return [{"domain": "none", "question": r["question"]} for r in read_csv(UNANSWERABLE_PATH)]
    if dataset in ("table", "image"):  # 표·이미지(차트 등)를 보고 답하는 문항. 검수하지 않았다
        return [
            {**r, "evidence": ""}
            for r in csv.DictReader(SOURCE_PATH.open(encoding="utf-8-sig"))
            if r["context_type"] == dataset and r["target_page_no"].strip().isdigit()
        ]
    used = {r["question"] for r in read_csv(VERIFIED_PATH) + read_csv(REJECTED_PATH)}  # 검수 통과·탈락 문항은 제외
    return [
        {**r, "evidence": ""}
        for r in csv.DictReader(SOURCE_PATH.open(encoding="utf-8-sig"))
        if r["context_type"] in ("paragraph", "text") and r["target_page_no"].strip().isdigit() and r["question"] not in used
    ]


def first_rank(chunks, row, by_file_only=False):
    for rank, c in enumerate(chunks, start=1):
        if c["file_name"] == row["target_file_name"] and (by_file_only or c["page_no"] == int(row["target_page_no"])):
            return rank
    return None


def squash(text):
    return "".join(text.split())


def has_evidence(chunks, row, window=15):
    """청크 중에 근거 구절의 연속 15자를 담은 것이 있는가 (줄바꿈·공백 무시)."""
    ev = squash(row.get("evidence", ""))
    if len(ev) < window:
        return None
    windows = [ev[i : i + window] for i in range(0, len(ev) - window + 1, 5)]
    return any(w in squash(c["content"]) for c in chunks for w in windows)


def load_json(path):
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else {}


# ---------- 검색 평가 (LLM 호출 없음) ----------
def eval_retrieval(method, chunk_size, chunk_overlap, dataset="verified", tables=False):
    RESULT_DIR.mkdir(exist_ok=True)
    path = RESULT_DIR / "retrieval.json"
    cache = load_json(path)
    key = f"{dataset}|{method}|{chunk_size}|{chunk_overlap}|{tables}"
    if key not in cache:
        rows = load_golden(dataset)
        ranks, file_ranks, prec, ev, times = [], [], [], [], []
        for row in rows:
            start = time.time()
            chunks = tools.search(row["question"], RETRIEVE_K, method, chunk_size, chunk_overlap, tables)
            times.append(time.time() - start)
            ranks.append(first_rank(chunks, row))
            file_ranks.append(first_rank(chunks[:K], row, by_file_only=True))
            prec.append(sum(c["file_name"] == row["target_file_name"] and c["page_no"] == int(row["target_page_no"]) for c in chunks[:K]) / K)
            ev.append(has_evidence(chunks[:K], row))
        n = len(rows)
        ev = [e for e in ev if e is not None]
        cache[key] = {
            "dataset": dataset,
            "method": method,
            "chunk": f"{chunk_size}/{chunk_overlap}",
            "tables": tables,
            "n": n,
            "hit@1": round(sum(r == 1 for r in ranks) / n, 3),
            "hit@3": round(sum(r is not None and r <= 3 for r in ranks) / n, 3),
            "hit@5": round(sum(r is not None and r <= 5 for r in ranks) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
            "precision@5": round(sum(prec) / n, 3),
            "file_hit@5": round(sum(r is not None for r in file_ranks) / n, 3),
            "evidence_hit@5": round(sum(ev) / len(ev), 3) if ev else None,
            "avg_ms": round(sum(times) / n * 1000),
        }
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf8")
    return cache[key]


def compare_retrieval(configs, datasets=("verified", "extra")):
    """configs: [(method, chunk_size, chunk_overlap) 또는 (..., tables), ...] → 설정×골든셋 비교표"""
    return pd.DataFrame([eval_retrieval(*c[:3], d, *c[3:]) for d in datasets for c in configs])


# ---------- 답변 평가 ----------
class Verdict(BaseModel):
    verdict: Literal["correct", "partial", "wrong"] = Field(description="기준 답변과 비교한 모델 답변의 정확성")
    faithfulness: Literal["yes", "partial", "no"] = Field(description="답변의 주장이 검색 결과로 뒷받침되는가")
    reason: str = Field(description="판정 이유 한 문장")


class Declined(BaseModel):
    declined: bool = Field(description="답변이 내용을 단정해 알려주지 않고 '문서에서 찾지 못했다/모른다'고 하면 true")


judge = agent.llm.with_structured_output(Verdict)
decline_judge = agent.llm.with_structured_output(Declined)


def basic_rag(question):
    """기본 RAG: 한 번 검색하고 바로 답한다 (근거 판단·재검색·보류 없음)."""
    start = time.time()
    chunks = tools.search(question, agent.TOP_K)
    chain = agent.answer_prompt | agent.llm | StrOutputParser()
    text = chain.invoke({"question": question, "context": agent.format_context(chunks)})
    return {"status": "answered", "answer": text, "queries": [question], "chunks": chunks, "elapsed_sec": round(time.time() - start, 2)}


def agent_rag(question):
    return agent.run(question, save=False)


def token_f1(pred, ref):
    p, r = tools.tokenize(pred), tools.tokenize(ref)
    common = sum((Counter(p) & Counter(r)).values())
    if not common:
        return 0.0
    precision, recall = common / len(p), common / len(r)
    return 2 * precision * recall / (precision + recall)


def score_answer(record, row, dataset):
    base = {
        "question": row["question"],
        "domain": row["domain"],
        "status": record["status"],
        "answer": record["answer"],
        "queries": record["queries"],
        "retrieved": [c["chunk_id"] for c in record["chunks"]],
        "elapsed_sec": record["elapsed_sec"],
    }
    if dataset == "unanswerable":  # 답하지 않는 것이 정답
        declined = True if record["status"] == "withheld" else decline_judge.invoke(f"질문: {row['question']}\n답변: {record['answer']}").declined
        return {**base, "declined": declined}

    chunks = record["chunks"]
    cited_pages = {int(p) for p in re.findall(r"p\.\s*(\d+)", record["answer"])}
    first_batch = chunks[: agent.TOP_K]  # 첫 검색 결과 (재검색 결과는 뒤에 이어 붙는다)
    scored = {
        "hit": first_rank(chunks, row) is not None,
        "first_hit": first_rank(first_batch, row) is not None,
        "cite_ok": record["status"] == "answered" and row["target_file_name"] in record["answer"] and int(row["target_page_no"]) in cited_pages,
        "token_f1": round(token_f1(record["answer"], row["target_answer"]), 3) if record["status"] == "answered" else 0.0,
    }
    if record["status"] == "withheld":
        return {**base, **scored, "verdict": "wrong", "faithfulness": None, "reason": "답변 보류"}
    result = judge.invoke(
        f"""모델 답변을 두 가지로 판정하라.
1) verdict: 기준 답변과 비교. correct=핵심 내용이 모두 맞다, partial=일부만 맞거나 핵심이 빠졌다, wrong=틀렸거나 답하지 못했다.
2) faithfulness: 모델 답변의 주장이 아래 검색 결과로 뒷받침되는가. yes=모두 뒷받침, partial=일부만, no=검색 결과에 없는 내용이 많다.

질문: {row['question']}
기준 답변: {row['target_answer']}
모델 답변: {record['answer']}

검색 결과:
{agent.format_context(chunks)}"""
    )
    return {**base, **scored, "verdict": result.verdict, "faithfulness": result.faithfulness, "reason": result.reason}


def run_system(name, fn, dataset="verified"):
    """fn(question) -> record 를 골든셋에 돌려 eval_results/{name}__{dataset}.json에 저장한다. 끝난 질문은 건너뛴다."""
    RESULT_DIR.mkdir(exist_ok=True)
    path = RESULT_DIR / f"{name}__{dataset}.json"
    results = load_json(path)
    lock = Lock()

    def work(row):
        return row["question"], score_answer(fn(row["question"]), row, dataset)

    todo = [r for r in load_golden(dataset) if r["question"] not in results]
    with ThreadPoolExecutor(WORKERS) as pool:
        for future in as_completed([pool.submit(work, r) for r in todo]):
            question, result = future.result()
            with lock:
                results[question] = result
                path.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf8")
    return summarize(name, dataset)


def rows_of(name, dataset):
    return list(load_json(RESULT_DIR / f"{name}__{dataset}.json").values())


def percentile(values, q):
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


def summarize(name, dataset="verified"):
    rows = rows_of(name, dataset)
    n = len(rows)
    times = [r["elapsed_sec"] for r in rows]
    common = {"system": name, "dataset": dataset, "n": n, "avg_sec": round(sum(times) / n, 1), "p95_sec": percentile(times, 0.95),
              "avg_searches": round(sum(len(r["queries"]) for r in rows) / n, 2)}
    if dataset == "unanswerable":
        return {**common, "refusal_rate": round(sum(r["declined"] for r in rows) / n, 3)}
    answered = [r for r in rows if r["status"] == "answered"]
    faith = [FAITH_SCORE[r["faithfulness"]] for r in answered]
    missed_first = [r for r in rows if not r["first_hit"]]
    return {
        **common,
        "first_hit": round(sum(r["first_hit"] for r in rows) / n, 3),
        "hit": round(sum(r["hit"] for r in rows) / n, 3),
        "accuracy": round(sum(VERDICT_SCORE[r["verdict"]] for r in rows) / n, 3),
        "faithfulness": round(sum(faith) / max(len(faith), 1), 3),
        "token_f1": round(sum(r["token_f1"] for r in rows) / n, 3),
        "cite_ok": round(sum(r["cite_ok"] for r in answered) / max(len(answered), 1), 3),
        "answered": round(len(answered) / n, 3),
        "recovered": round(sum(r["hit"] for r in missed_first) / len(missed_first), 3) if missed_first else None,  # 첫 검색을 놓친 질문 중 재검색으로 찾은 비율
    }


def compare_systems(names, datasets=("verified", "extra", "unanswerable")):
    return pd.DataFrame([summarize(n, d) for d in datasets for n in names])


def by_domain(names, dataset="verified"):
    """도메인별 accuracy"""
    scores = lambda n: pd.DataFrame(rows_of(n, dataset)).assign(score=lambda d: d.verdict.map(VERDICT_SCORE)).groupby("domain").score.mean().round(3)
    return pd.DataFrame({n: scores(n) for n in names})


def failure_breakdown(names, dataset="verified"):
    """틀린 답을 원인별로 센다: 검색 실패(정답 페이지를 못 찾음) / 생성 실패(찾았는데 틀림) / 보류"""
    out = {}
    for n in names:
        rows = [r for r in rows_of(n, dataset) if r["verdict"] != "correct"]
        out[n] = {
            "정답 아님(전체)": len(rows),
            "검색 실패": sum(not r["hit"] and r["status"] == "answered" for r in rows),
            "생성 실패": sum(r["hit"] and r["status"] == "answered" for r in rows),
            "보류": sum(r["status"] == "withheld" for r in rows),
        }
    return pd.DataFrame(out).T


def show_failures(name, dataset="verified", limit=5):
    rows = [r for r in rows_of(name, dataset) if r["verdict"] == "wrong"]
    return pd.DataFrame(rows)[["domain", "question", "status", "hit", "reason"]].head(limit) if rows else pd.DataFrame()


def win_loss(a, b, dataset="verified"):
    """질문별 verdict 점수로 시스템 a가 b보다 나은/같은/못한 질문 수"""
    ra = {r["question"]: VERDICT_SCORE[r["verdict"]] for r in rows_of(a, dataset)}
    rb = {r["question"]: VERDICT_SCORE[r["verdict"]] for r in rows_of(b, dataset)}
    diffs = [ra[q] - rb[q] for q in ra if q in rb]
    return {"better": sum(d > 0 for d in diffs), "same": sum(d == 0 for d in diffs), "worse": sum(d < 0 for d in diffs)}
