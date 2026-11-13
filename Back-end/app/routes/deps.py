from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from ..db import SessionLocal
from ..models import Session, User, utcnow
from ..security import COOKIE_NAME, hash_token


def get_db():
    with SessionLocal() as db:
        yield db


def current_user(
    session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: DbSession = Depends(get_db),
) -> User:
    user = None
    if session:
        user = db.scalar(
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(Session.token_hash == hash_token(session), Session.expires_at > utcnow())
        )
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in.")
    return user
