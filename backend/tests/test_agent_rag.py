from types import SimpleNamespace

import pytest

from app.agent import evaluate  # noqa: F401
from app.agent import rag


@pytest.mark.parametrize("source_ids", [[], [0], [1, 2]])
def test_rag_withholds_unverifiable_sources(monkeypatch, source_ids):
    monkeypatch.setattr(rag, "answerer", SimpleNamespace(invoke=lambda _: {
        "parsed": rag.GroundedAnswer(answer="자료에서 확인했어요.", source_ids=source_ids),
    }))
    state = {"question": "수수료가 있어요?", "chunks": [{"text": "수수료는 없어요.", "metadata": {"doc": "내금고 FAQ"}}]}
    assert rag.answer(state)["status"] == "withheld"


def test_rag_uses_exact_source_names_from_retrieval(monkeypatch):
    def invoke(prompt):
        assert "1. [내금고 자주 묻는 질문]" in prompt
        return {"parsed": rag.GroundedAnswer(answer="이체 수수료는 없어요.\n근거: 임의 제목", source_ids=[1, 1])}

    monkeypatch.setattr(rag, "answerer", SimpleNamespace(invoke=invoke))
    state = {"question": "수수료가 있어요?", "chunks": [
        {"text": "수수료는 없어요.", "metadata": {"doc": "내금고 자주 묻는 질문"}},
    ]}
    assert rag.answer(state) == {
        "answer": "이체 수수료는 없어요.\n\n근거: 내금고 자주 묻는 질문",
        "status": "answered",
    }
