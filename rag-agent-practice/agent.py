"""RAG Agent: 검색 → 근거 판단 → (부족하면 검색어 수정 후 재검색, 최대 3회) → 답변 또는 보류.

실행(이 폴더에서): python agent.py "질문"
실행 결과는 runs.jsonl에 한 줄씩 저장된다.
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from tools import search_documents

MODEL_NAME = "gemini-3.6-flash"
MAX_SEARCHES = 3  # 최초 검색 포함
TOP_K = 5
RUNS_PATH = Path(__file__).parent / "runs.jsonl"

llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0)


class Grade(BaseModel):
    sufficient: bool = Field(description="검색된 청크만으로 질문에 답할 수 있으면 true")
    reason: str = Field(description="판단 이유. 부족하면 무엇이 빠졌는지")


grader = llm.with_structured_output(Grade)

grade_prompt = ChatPromptTemplate.from_template(
    """질문에 답하는 데 필요한 내용이 아래 검색 결과에 들어 있는지 판단하라.
관련 주제만 언급될 뿐 질문이 묻는 구체적인 내용이 없으면 부족한 것이다.

질문: {question}

검색 결과:
{context}"""
)
rewrite_prompt = ChatPromptTemplate.from_template(
    """질문에 답할 근거를 문서에서 찾지 못했다. 다른 검색어 하나만 출력하라.
문서에 나올 법한 핵심 용어로 바꾸고, 이전과 같은 검색어는 피하라.

질문: {question}
이전 검색어: {queries}
부족했던 이유: {reason}"""
)
answer_prompt = ChatPromptTemplate.from_template(
    """검색 결과만 근거로 질문에 한국어로 답하라. 결과에 없는 내용은 추측하지 마라.
각 주장 뒤에 출처를 [파일명, p.페이지] 형식으로 붙여라.

질문: {question}

검색 결과:
{context}"""
)


class State(TypedDict):
    question: str
    query: str  # 현재 검색어
    queries: list[str]  # 지금까지 쓴 검색어
    chunks: list[dict]  # 검색된 청크 (중복 제거, 누적)
    sufficient: bool
    reason: str
    answer: str
    status: str  # answered | withheld


def format_context(chunks):
    return "\n\n".join(f"[{c['file_name']}, p.{c['page_no']}]\n{c['content']}" for c in chunks)


def retrieve(state: State):
    hits = search_documents.invoke({"query": state["query"], "k": TOP_K})
    seen = {c["chunk_id"] for c in state["chunks"]}
    new = [h for h in hits if h["chunk_id"] not in seen]
    return {"chunks": state["chunks"] + new, "queries": state["queries"] + [state["query"]]}


def grade(state: State):
    result = grader.invoke(grade_prompt.format_messages(question=state["question"], context=format_context(state["chunks"])))
    return {"sufficient": result.sufficient, "reason": result.reason}


def rewrite(state: State):
    chain = rewrite_prompt | llm | StrOutputParser()
    query = chain.invoke({"question": state["question"], "queries": state["queries"], "reason": state["reason"]})
    return {"query": query.strip()}


def answer(state: State):
    chain = answer_prompt | llm | StrOutputParser()
    text = chain.invoke({"question": state["question"], "context": format_context(state["chunks"])})
    return {"answer": text, "status": "answered"}


def withhold(state: State):
    msg = f"문서에서 충분한 근거를 찾지 못해 답변을 보류합니다. (검색 {len(state['queries'])}회, 이유: {state['reason']})"
    return {"answer": msg, "status": "withheld"}


def route_after_grade(state: State):
    if state["sufficient"]:
        return "answer"
    return "rewrite" if len(state["queries"]) < MAX_SEARCHES else "withhold"


builder = StateGraph(State)
builder.add_node("retrieve", retrieve)
builder.add_node("grade", grade)
builder.add_node("rewrite", rewrite)
builder.add_node("answer", answer)
builder.add_node("withhold", withhold)
builder.add_edge(START, "retrieve")
builder.add_edge("retrieve", "grade")
builder.add_conditional_edges("grade", route_after_grade, ["answer", "rewrite", "withhold"])
builder.add_edge("rewrite", "retrieve")
builder.add_edge("answer", END)
builder.add_edge("withhold", END)
graph = builder.compile()


def run(question: str, save: bool = True) -> dict:
    """질문 하나를 처리하고 결과를 runs.jsonl에 저장한다 (save=False면 저장하지 않는다)."""
    start = time.time()
    state = graph.invoke(
        {"question": question, "query": question, "queries": [], "chunks": [], "sufficient": False, "reason": "", "answer": "", "status": ""}
    )
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "question": question,
        "status": state["status"],
        "answer": state["answer"],
        "queries": state["queries"],
        "chunks": [{k: c[k] for k in ("chunk_id", "file_name", "page_no", "content")} for c in state["chunks"]],
        "elapsed_sec": round(time.time() - start, 2),
    }
    if save:
        with RUNS_PATH.open("a", encoding="utf8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


if __name__ == "__main__":
    result = run(sys.argv[1])
    print(f"[{result['status']}] 검색 {len(result['queries'])}회 {result['queries']} / {result['elapsed_sec']}초")
    print(result["answer"])
