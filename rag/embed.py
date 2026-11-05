"""chunks.jsonl → Gemini 임베딩 → data/rag/index/ (vectors.npy + chunks.jsonl 사본)

- 모델: gemini-embedding-2 (3072차원). 문서는 RETRIEVAL_DOCUMENT, 질문은 RETRIEVAL_QUERY로 임베딩한다.
- 캐시: 청크 본문의 sha1을 키로 벡터를 cache.npz에 저장한다. chunk.py를 고쳐 다시 돌려도 바뀐 청크만 API를 부른다.
- 벡터 DB 없이 numpy 행렬로 검색한다. ponytail: 청크 ~1천 개라 전수 내적이 1ms 안쪽. 수십만 개가 되면 Chroma/FAISS로 교체.
- 키: 프로젝트 .env의 GEMINI_API_KEY (GOOGLE_API_KEY는 무효라 쓰지 않는다).

실행 (bank_clone 폴더에서)
    python rag/embed.py                    # 임베딩·인덱스 생성 (이어서 실행 가능)
    python rag/embed.py "예금자보호 한도"   # 검색 테스트 (상위 5개)
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import dotenv_values
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data" / "rag" / "chunks.jsonl"
INDEX = ROOT / "data" / "rag" / "index"
MODEL = "gemini-embedding-2"
BATCH = 100  # 요청 1회당 최대 입력 수


def client():
    return genai.Client(api_key=dotenv_values(ROOT / ".env")["GEMINI_API_KEY"])


def embed(c, texts, task):
    for attempt in range(5):  # 429·503 같은 일시 오류는 백오프 후 재시도
        try:
            # 문자열 리스트를 그대로 넘기면 gemini-embedding-2가 한 문서로 합쳐 벡터 1개만 준다 → 텍스트마다 Content로 감싼다
            contents = [types.Content(parts=[types.Part(text=t)]) for t in texts]
            r = c.models.embed_content(model=MODEL, contents=contents, config=types.EmbedContentConfig(task_type=task))
            v = np.array([e.values for e in r.embeddings], dtype=np.float32)
            return v / np.linalg.norm(v, axis=1, keepdims=True)  # 정규화해 두면 내적 = 코사인 유사도
        except Exception as e:
            if attempt == 4:
                raise
            print(f"  retry {attempt + 1}: {str(e)[:80]}")
            time.sleep(2 ** (attempt + 1))


def build():
    rows = [json.loads(line) for line in CHUNKS.open(encoding="utf-8")]
    INDEX.mkdir(parents=True, exist_ok=True)
    cache_path = INDEX / "cache.npz"
    cache = dict(np.load(cache_path)) if cache_path.exists() else {}
    keys = [hashlib.sha1(r["text"].encode()).hexdigest() for r in rows]
    todo = [i for i, k in enumerate(keys) if k not in cache]
    print(f"{len(rows)} chunks, {len(rows) - len(todo)} cached, {len(todo)} to embed")
    c = client()
    for s in range(0, len(todo), BATCH):
        part = todo[s : s + BATCH]
        for i, v in zip(part, embed(c, [rows[i]["text"] for i in part], "RETRIEVAL_DOCUMENT"), strict=True):
            cache[keys[i]] = v
        np.savez(cache_path, **cache)  # 배치마다 저장 → 중간에 끊겨도 이어서
        print(f"  {min(s + BATCH, len(todo))}/{len(todo)}")
    np.save(INDEX / "vectors.npy", np.stack([cache[k] for k in keys]))
    (INDEX / "chunks.jsonl").write_text(CHUNKS.read_text(encoding="utf-8"), encoding="utf-8")  # 벡터 행 순서와 맞춘 사본
    print(f"index: {INDEX.relative_to(ROOT)} ({len(rows)} x {cache[keys[0]].shape[0]})")


def search(query, k=5, c=None):
    """질문과 코사인 유사도가 높은 청크 k개. 반환: [{chunk_id, score, text, metadata}]"""
    vectors = np.load(INDEX / "vectors.npy")
    rows = [json.loads(line) for line in (INDEX / "chunks.jsonl").open(encoding="utf-8")]
    q = embed(c or client(), [query], "RETRIEVAL_QUERY")[0]
    scores = vectors @ q
    top = np.argsort(-scores)[:k]
    return [{**rows[i], "score": round(float(scores[i]), 4)} for i in top]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:
        for h in search(" ".join(sys.argv[1:])):
            print(f"{h['score']}  {h['chunk_id']}\n    {h['text'][:120].replace(chr(10), ' / ')}")
    else:
        build()
