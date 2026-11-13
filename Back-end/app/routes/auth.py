from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from ..config import settings
from ..models import Session, User
from ..security import (
    COOKIE_NAME,
    clear_failures,
    create_session,
    hash_password,
    hash_token,
    record_failure,
    too_many_failures,
    verify_password,
)
from .deps import current_user, get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    job_description: str
    avatar_updated_at: datetime | None


class RegisterBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name can't be empty")
        return value


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterBody, response: Response, db: DbSession = Depends(get_db)):
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
    token = create_session(db, user.id)
    db.commit()
    _set_cookie(response, token)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginBody, response: Response, db: DbSession = Depends(get_db)):
    email = body.email.lower()
    if too_many_failures(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(user.password_hash if user else None, body.password):
        record_failure(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    clear_failures(email)
    token = create_session(db, user.id)
    db.commit()
    _set_cookie(response, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: DbSession = Depends(get_db),
):
    if session:
        db.execute(delete(Session).where(Session.token_hash == hash_token(session)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
