from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AliasChoices, BaseModel, EmailStr, Field, model_validator
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import current_user
from app.services import auth, verification

router = APIRouter(tags=["auth"])
Purpose = Literal["SIGNUP", "UNLOCK_ACCOUNT", "RESET_PW"]


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    pin: str = Field(pattern=r"^[0-9]{6}$")
    user_name: str = Field(min_length=1, max_length=50, validation_alias=AliasChoices("user_name", "name"))
    phone_num: str | None = Field(default=None, pattern=r"^01[0-9]{8,9}$")
    agreed_term_ids: list[int]


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=64)


class PinLoginIn(BaseModel):
    email: EmailStr
    pin: str = Field(pattern=r"^[0-9]{6}$")


class CodeIn(BaseModel):
    email: EmailStr
    purpose: Purpose


class VerifyIn(CodeIn):
    code: str = Field(pattern=r"^[0-9]{6}$")


class ResetIn(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^[0-9]{6}$")
    new_password: str = Field(min_length=8, max_length=64)


class ProfileIn(BaseModel):
    user_name: str | None = Field(default=None, min_length=1, max_length=50)
    phone_num: str | None = Field(default=None, pattern=r"^01[0-9]{8,9}$")


class WithdrawIn(BaseModel):
    password: str | None = Field(default=None, max_length=64)
    pin: str | None = Field(default=None, pattern=r"^[0-9]{6}$")

    @model_validator(mode="after")
    def require_credentials(self):
        if self.password is None and self.pin is None:
            raise ValueError("비밀번호 또는 PIN을 입력해 주세요.")
        return self


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=64)
    new_password: str = Field(min_length=8, max_length=64)


class PinChangeIn(BaseModel):
    current_pin: str = Field(pattern=r"^[0-9]{6}$")
    new_pin: str = Field(pattern=r"^[0-9]{6}$")


def user_out(user: User) -> dict:
    return {k: getattr(user, k) for k in ("id", "email", "user_name", "phone_num", "created_at")}


@router.get("/auth/email-available")
def email_available(email: EmailStr, db: Session = Depends(get_db)):
    return {"available": auth.find_by_email(db, email) is None}


@router.post("/auth/codes")
def request_code(body: CodeIn, db: Session = Depends(get_db)):
    return verification.request_code(db, body.email, body.purpose)


@router.post("/auth/codes/verify")
def verify_code(body: VerifyIn, db: Session = Depends(get_db)):
    verification.verify_code(db, body.email, body.purpose, body.code)
    db.commit()
    return {"verified": True}


@router.get("/terms")
def terms(category: Literal["SIGNUP", "ACCOUNT_OPEN"], db: Session = Depends(get_db)):
    return [{k: getattr(t, k) for k in ("id", "title", "version", "required", "content")} for t in auth.list_terms(db, category)]


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, db: Session = Depends(get_db)):
    return {"id": auth.signup(db, **body.model_dump()).id}


@router.post("/auth/demo", status_code=201)
def start_demo(db: Session = Depends(get_db)):
    return auth.start_demo(db)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    return auth.login(db, body.email, body.password, use_pin=False,
                      ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))


@router.post("/auth/login/pin")
def login_pin(body: PinLoginIn, request: Request, db: Session = Depends(get_db)):
    return auth.login(db, body.email, body.pin, use_pin=True,
                      ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))


@router.post("/auth/password/reset", status_code=204)
def reset_password(body: ResetIn, db: Session = Depends(get_db)):
    auth.reset_password(db, body.email, body.code, body.new_password)
    return Response(status_code=204)


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_out(auth.update_profile(db, user, body.model_dump(exclude_none=True)))


@router.delete("/me", status_code=204)
def withdraw(body: WithdrawIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    auth.withdraw(db, user, body.password, pin=body.pin)
    return Response(status_code=204)


@router.put("/me/password", status_code=204)
def change_password(body: PasswordChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    auth.change_password(db, user, body.current_password, body.new_password)
    return Response(status_code=204)


@router.put("/me/pin", status_code=204)
def change_pin(body: PinChangeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    auth.change_pin(db, user, body.current_pin, body.new_pin)
    return Response(status_code=204)
