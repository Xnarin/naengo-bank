"""AI 어시스턴트 API (docs/agent-design.md §5, §8). 프론트 계약(src/api/chat.ts): {message, context} → {blocks, context}

- 로그인 없이: 금융 질문(RAG)만 답하고, 조회·이체·카드는 intent만 돌려줘 프론트 Mock이 처리한다.
- 로그인(Bearer) 시: 전체 에이전트. 송금·카드 정지는 응답에 confirm(표시값)이 오고, POST /agent/confirm 에 PIN을 보내야 실행된다.
- PIN은 그래프(LLM)로 가지 않는다. 여기서 verify_pin 후 approved: bool 만 넘긴다.
- thread_id 는 만든 사용자에게 묶인다. 다른 사용자의 thread 는 거부.
"""

import uuid

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.graph import graph, resume, run, to_blocks
from app.db import get_db
from app.errors import BankError
from app.models import Account, User
from app.security import _bearer, current_user_id, verify_pin

router = APIRouter(prefix="/agent", tags=["agent"])
# ponytail: thread 소유자를 메모리에 둔다 (체크포인터도 메모리라 수명이 같다). PostgresSaver로 바꿀 때 테이블로
THREAD_OWNER: dict[str, uuid.UUID | None] = {}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    context: dict = {}
    thread_id: str | None = None


class ConfirmIn(BaseModel):
    thread_id: str
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
    return {"blocks": to_blocks(s), "context": context, "intent": s.get("intent"), "thread_id": s["thread_id"],
            "status": s.get("status"), "confirm": s.get("confirm")}


@router.post("/chat")
async def chat(body: ChatIn, user_id: uuid.UUID | None = Depends(optional_user_id), db: Session = Depends(get_db)):
    thread_id = owned_thread(body.thread_id, user_id)
    s = await run_in_threadpool(run, body.message, thread_id=thread_id, db=db, user_id=user_id)  # LLM 호출이 동기
    return out(s, body.context)


@router.post("/confirm")
async def confirm(body: ConfirmIn, user_id: uuid.UUID = Depends(current_user_id), db: Session = Depends(get_db)):
    owned_thread(body.thread_id, user_id)
    state = graph.get_state({"configurable": {"thread_id": body.thread_id}})
    pending = state.values.get("pending_action")
    if not state.interrupts or not pending:  # 이미 처리했거나 확인할 요청이 없음 → 두 번 실행 방지
        raise BankError("NO_PENDING", "확인할 요청이 없어요. 다시 요청해 주세요.", 409)
    if body.approved:
        if not body.pin:
            raise BankError("PIN", "비밀번호(PIN)를 입력해 주세요.")
        account = db.get(Account, uuid.UUID(pending["from_account_id"])) if pending.get("type") == "TRANSFER" else None
        verify_pin(db, db.get(User, user_id), body.pin, account)  # 틀리면 BankError (5회면 계좌 거래중지)
    s = await run_in_threadpool(resume, body.thread_id, body.approved, db=db, user_id=user_id)
    return out(s, {})
