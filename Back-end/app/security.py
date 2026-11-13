import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import settings
from .models import Session, utcnow

COOKIE_NAME = "session"
_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("no such user")

MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 15 * 60
_failures: dict[str, deque[float]] = defaultdict(deque)
_failures_lock = threading.Lock()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Takes about the same time whether or not the account exists."""
    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return stored_hash is not None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user_id: int) -> str:
    """Store only a hash of the login token, so a database leak can't be used to log in."""
    token = secrets.token_urlsafe(32)
    db.add(
        Session(
            token_hash=hash_token(token),
            user_id=user_id,
            expires_at=utcnow() + timedelta(days=settings.session_days),
        )
    )
    return token


def too_many_failures(email: str) -> bool:
    now = time.monotonic()
    with _failures_lock:
        attempts = _failures[email]
        while attempts and now - attempts[0] > FAILURE_WINDOW_SECONDS:
            attempts.popleft()
        if not attempts:
            del _failures[email]
            return False
        return len(attempts) >= MAX_FAILURES


def record_failure(email: str) -> None:
    with _failures_lock:
        _failures[email].append(time.monotonic())


def clear_failures(email: str) -> None:
    with _failures_lock:
        _failures.pop(email, None)
