"""AI 어시스턴트 API (docs/agent-design.md §5, §8). 프론트 계약(src/api/chat.ts): {message, context} → {blocks, context}

- 로그인 없이: 금융 질문(RAG)만 답하고, 조회·이체·카드는 intent만 돌려줘 프론트 Mock이 처리한다.
- 로그인(Bearer) 시: 송금·카드 조치는 응답의 confirmation_id와 PIN을 POST /agent/confirm에 보내야 실행된다.
- PIN은 그래프(LLM)로 가지 않는다. 여기서 verify_pin 후 approved: bool 만 넘긴다.
- thread_id 는 만든 사용자에게 묶인다. 다른 사용자의 thread 는 거부.
"""

import uuid
from contextlib import contextmanager
from threading import Lock

from fastapi import APIRouter, Depends, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.graph import graph, resume, run, to_blocks
from app.db import get_db
from app.errors import BankError
from app.models import Account, User
from app.security import _bearer, current_user_id, verify_pin
from app.services.transfers import find_owned_transfer

router = APIRouter(prefix="/agent", tags=["agent"])
# ponytail: thread 소유자를 메모리에 둔다 (체크포인터도 메모리라 수명이 같다). PostgresSaver로 바꿀 때 테이블로
THREAD_OWNER: dict[str, uuid.UUID | None] = {}
_busy_threads: set[str] = set()
_busy_lock = Lock()


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    context: dict = {}
    thread_id: str | None = None


class ConfirmIn(BaseModel):
    thread_id: str
    confirmation_id: uuid.UUID
    approved: bool
    pin: str | None = Field(None, min_length=6, max_length=6)


def optional_user_id(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> uuid.UUID | None:
    return current_user_id(cred, db) if cred else None


def owned_thread(thread_id: str | None, user_id: uuid.UUID | None) -> str:
    if thread_id is None:
        thread_id = str(uuid.uuid4())
        THREAD_OWNER[thread_id] = user_id
    elif THREAD_OWNER.get(thread_id, user_id) != user_id or thread_id not in THREAD_OWNER:
        raise BankError("AUTH", "대화를 찾을 수 없어요. 새 대화를 시작해 주세요.", 404)
    return thread_id


def out(s: dict, context: dict) -> dict:
    pending = s["pending_action"] if s.get("status") == "confirm" else {}
    return {"blocks": to_blocks(s), "context": context, "intent": s.get("intent"), "thread_id": s["thread_id"],
            "status": s.get("status"), "confirm": s.get("confirm"), "confirmation_id": pending.get("confirmation_id"),
            "confirmation_type": pending.get("type")}


@contextmanager
def thread_operation(thread_id: str):
    # Keep the guard in the worker until the graph call finishes, even if the client disconnects.
    with _busy_lock:
        if thread_id in _busy_threads:
            raise BankError("THREAD_BUSY", "이 대화의 요청을 처리 중이에요. 잠시 후 다시 시도해 주세요.", 409)
        _busy_threads.add(thread_id)
    try:
        yield
    finally:
        with _busy_lock:
            _busy_threads.remove(thread_id)


@router.post("/chat")
def chat(body: ChatIn, user_id: uuid.UUID | None = Depends(optional_user_id), db: Session = Depends(get_db)):
    thread_id = owned_thread(body.thread_id, user_id)
    with thread_operation(thread_id):
        return out(run(body.message, thread_id=thread_id, db=db, user_id=user_id), body.context)


@router.post("/confirm")
def confirm(body: ConfirmIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    owned_thread(body.thread_id, user_id)
    with thread_operation(body.thread_id):
        state = graph.get_state({"configurable": {"thread_id": body.thread_id}})
        pending = state.values.get("pending_action")
        if not state.interrupts or not pending:
            raise BankError("NO_PENDING", "확인할 요청이 없어요. 다시 요청해 주세요.", 409)
        if pending.get("confirmation_id") != str(body.confirmation_id):
            raise BankError("STALE_CONFIRMATION", "이 확인은 만료됐어요. 새 확인 화면을 이용해 주세요.", 409)
        if body.approved:
            if not body.pin:
                raise BankError("PIN", "비밀번호(PIN)를 입력해 주세요.")
            account = (db.get(Account, uuid.UUID(pending["from_account_id"]))
                       if pending["type"] in ("TRANSFER", "AUTO_TRANSFER") else None)
            verify_pin(db, db.get(User, user_id), body.pin, account)
        return out(resume(body.thread_id, body.approved, db=db, user_id=user_id), {})


@router.get("/transfers/{confirmation_id}")
def transfer_result(confirmation_id: uuid.UUID, response: Response,
                    user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    result = find_owned_transfer(db, user_id, f"agent:{confirmation_id}")
    response.headers["Cache-Control"] = "no-store"
    return {"status": result.status, "amount": result.amount} if result else {"status": "UNKNOWN"}
