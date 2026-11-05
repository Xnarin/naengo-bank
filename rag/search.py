"""검색 방식 3가지: vector(embed.search) / bm25(Kiwi 형태소) / hybrid(두 순위를 RRF로 합침)

rag-agent-practice/tools.py와 같은 방식: 각 방식에서 후보 CANDIDATES개를 뽑고 1/(RRF_K+순위)를 더해 다시 정렬.

실행 (bank_clone 폴더에서)
    python rag/search.py hybrid "착오송금 반환"
"""

import json
import sys
from functools import lru_cache
from pathlib import Path

from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

sys.path.insert(0, str(Path(__file__).parent))
import embed  # noqa: E402

RRF_K = 60
CANDIDATES = 20


@lru_cache(maxsize=1)
def kiwi():
    return Kiwi()


def tokenize(text):
    # 명사·동사·형용사 어근·외국어·숫자만 (조사·어미·문장부호 제외)
    return [t.form for t in kiwi().tokenize(text) if t.tag[0] in "NVS" and t.tag not in ("SF", "SP", "SS", "SE", "SO", "SW")]


@lru_cache(maxsize=1)
def bm25_index():
    rows = [json.loads(line) for line in (embed.INDEX / "chunks.jsonl").open(encoding="utf-8")]
    return rows, BM25Okapi([tokenize(r["text"]) for r in rows])


def bm25(query, k=5):
    rows, index = bm25_index()
    scores = index.get_scores(tokenize(query))
    top = sorted(range(len(rows)), key=lambda i: -scores[i])[:k]
    return [{**rows[i], "score": round(float(scores[i]), 4)} for i in top]


def hybrid(query, k=5, c=None):
    fused, by_id = {}, {}
    for hits in (embed.search(query, CANDIDATES, c), bm25(query, CANDIDATES)):
        for rank, h in enumerate(hits, 1):
            fused[h["chunk_id"]] = fused.get(h["chunk_id"], 0) + 1 / (RRF_K + rank)
            by_id.setdefault(h["chunk_id"], h)
    top = sorted(fused, key=lambda cid: -fused[cid])[:k]
    return [{**by_id[cid], "score": round(fused[cid], 4)} for cid in top]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    method, query = sys.argv[1], " ".join(sys.argv[2:])
    for h in {"vector": embed.search, "bm25": bm25, "hybrid": hybrid}[method](query):
        print(f"{h['score']}  {h['chunk_id']}\n    {h['text'][:120].replace(chr(10), ' / ')}")
