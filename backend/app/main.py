from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from app.api import accounts, agent, auth, transfers
from app.errors import BankError
from app.db import get_db
from app.api import cards, auto_transfers, notifications
from app.config import settings
from app.scheduler import create_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = create_scheduler() if settings.scheduler_enabled else None
    if scheduler:
        scheduler.start()
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=True)


app = FastAPI(title="Bank Clone API", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(agent.router)
app.include_router(cards.router)
app.include_router(auto_transfers.router)
app.include_router(notifications.router)


@app.get("/health", tags=["health"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.exception_handler(RequestValidationError)
def invalid_input(_: Request, e: RequestValidationError):
    # FastAPI 기본 응답의 input 필드는 잘못 입력한 비밀번호/PIN도 그대로 돌려준다.
    return JSONResponse({"detail": [{k: error[k] for k in ("loc", "msg", "type")} for error in e.errors()]}, status_code=422)


@app.exception_handler(BankError)
def bank_error(_: Request, e: BankError):
    return JSONResponse({"code": e.code, "message": e.message}, status_code=e.status)
