import secrets
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session as DbSession

from app.config import settings
from app.db import SessionLocal
from app.models import Session, User, utcnow
from app.security import clear_failures, hash_token, record_failure, too_many_failures, verify_password

# Its own cookie name, so signing in here never touches a user's session on the main site.
COOKIE_NAME = "admin_session"
SESSION_HOURS = 12

router = APIRouter(prefix="/api/admin", tags=["auth"])


def get_db():
    with SessionLocal() as db:
        yield db


class AdminOut(BaseModel):
    id: int
    email: str
    name: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


def current_admin(
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> User:
    user = None
    if token:
        user = db.scalar(
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(Session.token_hash == hash_token(token), Session.expires_at > utcnow(), User.is_admin.is_(True))
        )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in.")
    return user


@router.post("/login", response_model=AdminOut)
def login(body: LoginBody, response: Response, db: DbSession = Depends(get_db)):
    email = body.email.lower()
    if too_many_failures(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please try again in 15 minutes.")
    user = db.scalar(select(User).where(User.email == email))
    password_ok = verify_password(user.password_hash if user else None, body.password)
    # The same answer for a wrong password and for a non-admin, so this can't be used to find admin emails.
    if not password_ok or not user.is_admin:
        record_failure(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    clear_failures(email)
    token = secrets.token_urlsafe(32)
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(hours=SESSION_HOURS),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_HOURS * 3600,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: DbSession = Depends(get_db),
):
    if token:
        db.execute(delete(Session).where(Session.token_hash == hash_token(token)))
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=AdminOut)
def me(admin: User = Depends(current_admin)):
    return admin
