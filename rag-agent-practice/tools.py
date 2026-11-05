"""검색 도구: 검색어로 상위 k개 청크를 찾아 ID·출처와 함께 반환한다.
검색 방식은 vector / bm25 / hybrid(RRF) 중에서 고른다.

실행(이 폴더에서): python tools.py "대장암 증상"
"""

import sys
from collections import Counter
from functools import lru_cache

from kiwipiepy import Kiwi
from langchain_core.tools import tool
from rank_bm25 import BM25Okapi

from ingest import get_vectorstore

# search_documents 도구가 쓰는 기본 설정. 비교 실험에서 고른 값으로 바꾼다.
SETTINGS = {"chunk_size": 500, "chunk_overlap": 50, "method": "vector", "tables": False}  # tables: 표 추출 인덱스(_tbl) 사용 여부
RRF_K = 60  # hybrid: 두 검색의 순위를 1/(RRF_K+순위)로 합친다
CANDIDATES = 20  # hybrid: 각 검색에서 가져올 후보 수


@lru_cache
def vectorstore(chunk_size, chunk_overlap, tables=False):
    return get_vectorstore(chunk_size, chunk_overlap, tables)


@lru_cache
def kiwi():
    return Kiwi()


def tokenize(text):
    """형태소 분석 후 명사·동사·영문·숫자만 쓴다 (조사·어미 제거)."""
    return [t.form for t in kiwi().tokenize(text) if t.tag[0] in "NVS" and t.tag not in ("SF", "SP", "SS", "SE", "SO", "SW")]


@lru_cache
def bm25_index(chunk_size, chunk_overlap, tables):
    data = vectorstore(chunk_size, chunk_overlap, tables)._collection.get(include=["documents", "metadatas"])
    return data, BM25Okapi([tokenize(text) for text in data["documents"]])


def to_hit(text, metadata, score):
    return {
        "chunk_id": metadata["chunk_id"],
        "file_name": metadata["file_name"],
        "page_no": metadata["page_no"],
        "content_type": metadata.get("content_type", "text"),
        "content": text,
        "score": round(score, 4),  # 클수록 관련도가 높다 (방식마다 단위는 다르다)
    }


@lru_cache(maxsize=None)
def query_vector(query):
    """질문 임베딩은 설정(청킹·검색 방식)과 무관하므로 한 번만 만든다."""
    return vectorstore(SETTINGS["chunk_size"], SETTINGS["chunk_overlap"], False)._embedding_function.embed_query(query)


def vector_search(query, k, chunk_size, chunk_overlap, tables):
    r = vectorstore(chunk_size, chunk_overlap, tables)._collection.query(
        query_embeddings=[query_vector(query)], n_results=k, include=["documents", "metadatas", "distances"]
    )
    return [to_hit(t, m, 1 - d) for t, m, d in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])]


def bm25_search(query, k, chunk_size, chunk_overlap, tables):
    data, bm25 = bm25_index(chunk_size, chunk_overlap, tables)
    scores = bm25.get_scores(tokenize(query))
    top = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)[:k]
    return [to_hit(data["documents"][i], data["metadatas"][i], float(scores[i])) for i in top]


def hybrid_search(query, k, chunk_size, chunk_overlap, tables):
    fused, by_id = Counter(), {}
    for search in (vector_search, bm25_search):
        for rank, hit in enumerate(search(query, CANDIDATES, chunk_size, chunk_overlap, tables), start=1):
            fused[hit["chunk_id"]] += 1 / (RRF_K + rank)
            by_id[hit["chunk_id"]] = hit
    return [{**by_id[cid], "score": round(s, 4)} for cid, s in fused.most_common(k)]


METHODS = {"vector": vector_search, "bm25": bm25_search, "hybrid": hybrid_search}


def search(query, k=5, method=None, chunk_size=None, chunk_overlap=None, tables=None):
    """인자를 생략하면 SETTINGS의 값을 쓴다."""
    return METHODS[method or SETTINGS["method"]](
        query,
        k,
        chunk_size or SETTINGS["chunk_size"],
        chunk_overlap or SETTINGS["chunk_overlap"],
        SETTINGS["tables"] if tables is None else tables,
    )


@tool
def search_documents(query: str, k: int = 5) -> list[dict]:
    """금융·공공·의료·법률·커머스 PDF에서 query와 관련된 청크를 상위 k개 검색한다.
    각 결과에 chunk_id, file_name, page_no, content, score(클수록 관련도 높음)가 들어 있다."""
    return search(query, k)


if __name__ == "__main__":
    for method in METHODS:
        hits = search(sys.argv[1], 3, method)
        assert len(hits) == 3 and all(h["chunk_id"] and h["page_no"] >= 1 for h in hits)
        print(f"== {method}")
        for h in hits:
            print(h["score"], h["file_name"], f"p{h['page_no']}", h["content"][:60].replace("\n", " "))
