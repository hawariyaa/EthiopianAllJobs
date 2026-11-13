from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

THIS_WEEK_DAYS = 7
LISTED_DAYS = 21  # 7 days in This Week, then 14 in Past Two Weeks
LINKEDIN_SOURCE = "linkedin"  # kept apart from the other sites, in its own menu
LINKEDIN_DAYS = 14  # LinkedIn jobs stay listed for two weeks


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(255))
    job_description: Mapped[str] = mapped_column(Text, default="")
    # Bumped when the description changes, so jobs rejected under the old text can be rechecked.
    description_version: Mapped[int] = mapped_column(Integer, default=1)
    # Jobs collected before this are never checked for this user.
    matching_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Lets the account sign in to the separate admin site (see Admin/).
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Avatar(Base):
    __tablename__ = "avatars"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    image: Mapped[bytes] = mapped_column(LargeBinary)


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text)
    job_type: Mapped[str | None] = mapped_column(String(60))
    work_mode: Mapped[str | None] = mapped_column(String(60))
    experience_level: Mapped[str | None] = mapped_column(String(60))
    compensation: Mapped[str | None] = mapped_column(String(120))
    categories: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Match(Base):
    """The AI's verdict on one job for one user. `selected_at` is set once and starts the job's 21 days."""

    __tablename__ = "matches"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    description_version: Mapped[int] = mapped_column(Integer)
    is_match: Mapped[bool] = mapped_column(Boolean)
    score: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    job: Mapped[Job] = relationship()


class AiCall(Base):
    """One request to the AI for one user (retries included in `attempts`). Kept for the admin site."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # "screen" or "evaluate"
    model: Mapped[str] = mapped_column(String(120), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float | None] = mapped_column(Float)  # USD, when OpenRouter reports it
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CrawlRun(Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


def listed_since(now: datetime) -> datetime:
    return now - timedelta(days=LISTED_DAYS)


def linkedin_listed_since(now: datetime) -> datetime:
    return now - timedelta(days=LINKEDIN_DAYS)
