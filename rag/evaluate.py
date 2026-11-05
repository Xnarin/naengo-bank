"""골든셋(data/rag/golden.csv) 검수 + 검색 평가

골든셋 형식: targets = "파일::조문 또는 FAQ 제목" 을 ;로 이어 쓴다. 이 중 하나라도 검색되면 정답.
chunk_id(번호)는 청킹을 바꾸면 달라지므로 파일+조문/제목으로 정답을 고정한다.

실행 (bank_clone 폴더에서)
    python rag/evaluate.py check          # 정답 위치·근거 구절이 실제 청크에 있는지 검수
    python rag/evaluate.py vector [k]     # 벡터 검색 Hit@1/3/5, MRR, 근거 포함률 (기본 k=5)
    python rag/evaluate.py bm25|hybrid    # BM25(Kiwi) / 하이브리드(RRF) 같은 지표
    cd backend && uv run python ../rag/evaluate.py agent   # 에이전트 답변 채점 (LLM 판정) → eval_results/agent.json
"""

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "rag" / "golden.csv"
CHUNKS = ROOT / "data" / "rag" / "chunks.jsonl"
RESULTS = ROOT / "data" / "rag" / "eval_results"


def squash(t):
    return re.sub(r"\s+", "", t)


def load():
    golden = list(csv.DictReader(GOLDEN.open(encoding="utf-8-sig")))
    for g in golden:
        g["targets"] = [tuple(t.strip().split("::", 1)) for t in g["targets"].split(";") if t.strip()]
    return golden


def is_target(row, targets):
    m = row["metadata"]
    return any(m["file_name"] == f and ref in (m.get("article"), m.get("title")) for f, ref in targets)


def check():
    rows = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]
    bad = 0
    for g in load():
        if g["answerable"] != "Y":
            continue
        for t in g["targets"]:
            if not any(is_target(r, [t]) for r in rows):
                print(f"{g['id']} 정답 위치 없음: {t}")
                bad += 1
        primary = [r for r in rows if is_target(r, g["targets"][:1])]
        if not any(squash(g["evidence"]) in squash(r["text"]) for r in primary):
            print(f"{g['id']} 근거 구절이 첫 번째 정답 청크에 없음: {g['evidence']}")
            bad += 1
    print("검수 통과" if not bad else f"문제 {bad}건")
    review(rows)
    return bad


def review(rows):
    """사람이 원문과 대조할 검토지: 질문·기준 답변·근거 구절 + 정답 청크 원문 (근거 구절은 **굵게**)."""
    out = ["# 골든셋 검토지\n", "`python rag/evaluate.py check`가 다시 만듭니다. 고칠 내용은 golden.csv에 반영하세요.\n"]
    for g in load():
        out.append(f"## {g['id']} · {g['category']} · 답변 {'가능' if g['answerable'] == 'Y' else '불가'}\n")
        out.append(f"**질문** {g['question']}\n")
        if g["answerable"] != "Y":
            out.append(f"**메모** {g['note']}\n")
            continue
        out.append(f"**기준 답변** {g['target_answer']}\n\n**근거 구절** `{g['evidence']}`\n")
        for f, ref in g["targets"]:
            text = "\n\n".join(r["text"] for r in rows if is_target(r, [(f, ref)]))
            text = text.replace(g["evidence"], f"**{g['evidence']}**")
            out.append(f"<details><summary>정답 원문: {f} · {ref}</summary>\n\n{text}\n\n</details>\n")
    (GOLDEN.parent / "golden_review.md").write_text("\n".join(out), encoding="utf-8")


def evaluate(search, name, k=5):
    """search(question, k) -> 청크 리스트. 답할 수 있는 질문: Hit@k·MRR·근거 포함률. 답변 불가 질문: 1위 점수 (보류 임계값 참고용)."""
    golden = load()
    records, ranks = [], []
    for g in golden:
        hits = search(g["question"], k)
        rank = next((i + 1 for i, h in enumerate(hits) if is_target(h, g["targets"])), None)
        evid = g["answerable"] == "Y" and any(squash(g["evidence"]) in squash(h["text"]) for h in hits)
        records.append({"id": g["id"], "question": g["question"], "answerable": g["answerable"], "coverage": g.get("coverage", ""), "rank": rank, "evidence_hit": evid,
                        "top_score": hits[0].get("score"), "retrieved": [h["chunk_id"] for h in hits]})
        if g["answerable"] == "Y":
            ranks.append(rank)
    n = len(ranks)
    summary = {
        "method": name, "k": k, "n": n,
        **{f"hit@{j}": round(sum(1 for r in ranks if r and r <= j) / n, 3) for j in (1, 3, 5) if j <= k},
        "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
        f"evidence_hit@{k}": round(sum(r["evidence_hit"] for r in records) / n, 3),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{name}.json").write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary)
    groups = {"직접 작성(G)": lambda r: r["id"].startswith("G"), "실제 질문(R)": lambda r: r["id"].startswith("R"),
              "  └ 완전 답변": lambda r: r["id"].startswith("R") and r["coverage"] == "full", "  └ 부분 답변": lambda r: r["id"].startswith("R") and r["coverage"] == "partial"}
    for label, pick in groups.items():
        part = [r for r in records if r["answerable"] == "Y" and pick(r)]
        if part:
            h = lambda j: sum(1 for r in part if r["rank"] and r["rank"] <= j) / len(part)
            print(f"  {label:12} n={len(part):3}  hit@1 {h(1):.3f}  hit@{k} {h(k):.3f}  mrr {sum(1 / r['rank'] for r in part if r['rank']) / len(part):.3f}")
    print("놓친 질문:")
    for r in records:
        if r["answerable"] == "Y" and not r["rank"]:
            print(f"  {r['id']} {r['question']}  → {r['retrieved'][:3]}")
    ys = [r["top_score"] for r in records if r["answerable"] == "Y"]
    ns = [r["top_score"] for r in records if r["answerable"] == "N"]
    print(f"1위 점수: 답변 가능 최저 {min(ys)} / 평균 {sum(ys) / len(ys):.3f}, 답변 불가 {sorted(ns, reverse=True)}")
    return summary


JUDGE_PROMPT = """은행 챗봇 답변을 기준 답변과 비교해 채점하라.
- 정답: 기준 답변의 핵심(금액·기간·조건·가능 여부)이 맞고, 틀린 정보가 없다.
- 부분: 핵심 일부만 맞거나 중요한 내용이 빠졌다.
- 오답: 핵심이 틀렸거나 기준과 반대되는 정보를 준다. 질문 전체에 대해 답을 보류했으면 오답이다.
기준 답변이 다루지 않는 세부를 챗봇이 "확인이 어렵다"고 한 것은 감점하지 않는다 (기준 답변의 괄호 속 "데이터에 없음"도 같은 뜻).
표현 차이와 추가 설명은 감점하지 않는다. 다만 기준에 없는 내용을 사실처럼 단정하면 감점한다.

질문: {question}
기준 답변: {target}
챗봇 답변: {answer}"""


def evaluate_agent(workers=6):
    """에이전트 전체(router → RAG → 답변/보류) 평가. backend 가상환경에서 실행: cd backend && uv run python ../rag/evaluate.py agent"""
    from concurrent.futures import ThreadPoolExecutor
    from typing import Literal

    from pydantic import BaseModel

    sys.path.insert(0, str(ROOT / "backend"))
    from app.agent.graph import run
    from app.agent.rag import llm

    class Verdict(BaseModel):
        verdict: Literal["정답", "부분", "오답"]
        reason: str

    judge = llm.with_structured_output(Verdict)

    def one(g):
        s = run(g["question"])
        rec = {"id": g["id"], "question": g["question"], "answerable": g["answerable"], "coverage": g.get("coverage", ""),
               "intent": s["intent"], "status": s["status"], "searches": len(s.get("queries", [])), "answer": s["answer"],
               "target_answer": g["target_answer"], "retrieved_target": any(is_target(c, g["targets"]) for c in s.get("chunks", []))}
        if g["answerable"] == "Y":
            v = judge.invoke(JUDGE_PROMPT.format(question=g["question"], target=g["target_answer"], answer=s["answer"]))
            rec["verdict"], rec["judge_reason"] = v.verdict, v.reason
        return rec

    with ThreadPoolExecutor(workers) as ex:
        records = list(ex.map(one, load()))
    ys = [r for r in records if r["answerable"] == "Y"]
    ns = [r for r in records if r["answerable"] == "N"]
    rate = lambda rs, f: round(sum(map(f, rs)) / len(rs), 3) if rs else None
    summary = {"n_answerable": len(ys), "n_unanswerable": len(ns),
               "answered": rate(ys, lambda r: r["status"] == "answered"),
               "정답": rate(ys, lambda r: r["verdict"] == "정답"), "정답+부분": rate(ys, lambda r: r["verdict"] != "오답"),
               "abstain_on_unanswerable": rate(ns, lambda r: r["status"] != "answered"),
               "avg_searches": rate([r for r in records if r["searches"]], lambda r: r["searches"])}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "agent.json").write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary)
    for label, pick in {"직접 작성(G)": lambda r: r["id"][0] == "G", "실제 질문(R)": lambda r: r["id"][0] == "R",
                        "  └ 완전 답변": lambda r: r["id"][0] == "R" and r["coverage"] == "full", "  └ 부분 답변": lambda r: r["id"][0] == "R" and r["coverage"] == "partial"}.items():
        part = [r for r in ys if pick(r)]
        print(f"  {label:12} n={len(part):3}  답변 {rate(part, lambda r: r['status'] == 'answered')}  정답 {rate(part, lambda r: r['verdict'] == '정답')}  정답+부분 {rate(part, lambda r: r['verdict'] != '오답')}")
    print("오답·보류:")
    for r in ys:
        if r["verdict"] == "오답":
            print(f"  {r['id']} [{r['intent']}/{r['status']}] {r['question']} → {r['judge_reason'][:90]}")
    print("답변 불가 질문:", [(r["id"], r["intent"], r["status"]) for r in ns])
    return summary


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        sys.exit(1 if check() else 0)
    if cmd == "agent":
        evaluate_agent()
    if cmd in ("vector", "bm25", "hybrid"):
        sys.path.insert(0, str(Path(__file__).parent))
        import embed
        import search

        c = embed.client()
        fn = {"vector": lambda q, k: embed.search(q, k, c), "bm25": search.bm25, "hybrid": lambda q, k: search.hybrid(q, k, c)}[cmd]
        evaluate(fn, cmd, int(sys.argv[2]) if len(sys.argv) > 2 else 5)
