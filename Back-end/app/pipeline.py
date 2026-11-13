import logging
import threading
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, exists, select

from .config import settings
from .db import SessionLocal
from .matching import make_llm, match_user
from .models import LINKEDIN_SOURCE, AiCall, CrawlRun, Job, Match, Session, User, linkedin_listed_since, listed_since, utcnow
from .sources import SOURCES
from .sources.base import USER_AGENT, ScrapedJob, Source

log = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)
MAX_CATCH_UP = timedelta(days=7)
UNSELECTED_VERDICT_DAYS = 7

scrape_lock = threading.Lock()
match_lock = threading.Lock()
matching_users: set[int] = set()  # users waiting for or in an AI check; read by /api/status


def as_utc(value: datetime) -> datetime:
    """SQLite drops time zones; everything we store is UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _last_success(session, source: str) -> datetime | None:
    return session.scalar(
        select(CrawlRun.started_at)
        .where(CrawlRun.source == source, CrawlRun.finished_at.is_not(None), CrawlRun.error.is_(None))
        .order_by(CrawlRun.started_at.desc())
        .limit(1)
    )


def crawl_since(session, source: str, now: datetime) -> datetime:
    """Normally the past 24 hours; further back if a run was missed, so no jobs fall in a gap."""
    last = _last_success(session, source)
    if last is None:
        return now - WINDOW
    return max(now - MAX_CATCH_UP, min(now - WINDOW, as_utc(last)))


def needs_catch_up(session_factory, now: datetime) -> bool:
    with session_factory() as session:
        for source in SOURCES:
            last = _last_success(session, source.name)
            if last is None or now - as_utc(last) >= WINDOW:
                return True
    return False


def _upsert(session, source: str, scraped: ScrapedJob, seen_at: datetime) -> bool:
    """Save one job. True if it is new."""
    job = session.scalar(select(Job).where(Job.source == source, Job.external_id == scraped.external_id))
    is_new = job is None
    if is_new:
        job = Job(source=source, external_id=scraped.external_id, first_seen_at=seen_at)
        session.add(job)
    for field in (
        "title", "company", "location", "description", "url", "job_type", "work_mode",
        "experience_level", "compensation", "categories", "skills", "published_at", "deadline",
    ):
        setattr(job, field, getattr(scraped, field))
    return is_new


def crawl_source(session_factory, source: Source, client: httpx.Client, delay: float) -> CrawlRun:
    started = utcnow()
    with session_factory() as session:
        run = CrawlRun(source=source.name, started_at=started)
        since = crawl_since(session, source.name, started)
        session.add(run)
        session.commit()
        try:
            for scraped in source.fetch_jobs(client, delay, since):
                run.jobs_new += _upsert(session, source.name, scraped, started)
                run.jobs_seen += 1
                if run.jobs_seen % 50 == 0:
                    session.commit()
        except Exception as exc:
            log.exception("Crawl of %s failed", source.name)
            session.rollback()
            run = session.merge(run)
            run.error = str(exc)[:1000]
        run.finished_at = utcnow()
        session.commit()
    return run


def remove_expired(session_factory, now: datetime) -> None:
    """Drop selections past 21 days (14 for LinkedIn), old rejections, jobs nobody needs, and expired logins."""
    cutoff = listed_since(now)
    with session_factory() as session:
        session.execute(
            delete(Match).where(
                Match.selected_at < linkedin_listed_since(now),
                Match.job_id.in_(select(Job.id).where(Job.source == LINKEDIN_SOURCE)),
            )
        )
        session.execute(delete(Match).where(Match.selected_at < cutoff))
        session.execute(
            delete(Match).where(
                Match.selected_at.is_(None), Match.evaluated_at < now - timedelta(days=UNSELECTED_VERDICT_DAYS)
            )
        )
        session.execute(
            delete(Job).where(Job.first_seen_at < cutoff, ~exists().where(Match.job_id == Job.id))
        )
        session.execute(delete(Session).where(Session.expires_at < now))
        session.commit()


def _http_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)


def _ai_recorder(user_id: int):
    def record(fields: dict) -> None:
        with SessionLocal() as session:
            session.add(AiCall(user_id=user_id, **fields))
            session.commit()

    return record


def match_users(user_ids: list[int]) -> None:
    matching_users.update(user_ids)
    try:
        with match_lock, _http_client() as client:
            llm = make_llm(client)
            for user_id in user_ids:
                llm.usage_sink = _ai_recorder(user_id)  # users are matched one at a time
                try:
                    stats = match_user(SessionLocal, llm, user_id, settings.match_threshold)
                    log.info("Matched user %s: %s", user_id, stats)
                except Exception:
                    log.exception("Matching failed for user %s", user_id)
                matching_users.discard(user_id)
    finally:
        matching_users.difference_update(user_ids)


def start_matching_user(user_id: int) -> None:
    threading.Thread(target=match_users, args=([user_id],), daemon=True).start()


def daily_run() -> None:
    """Collect new jobs, check them for every user, then clear out what has aged off."""
    if not scrape_lock.acquire(blocking=False):
        log.info("Daily run skipped: one is already running")
        return
    try:
        with _http_client() as client:
            for source in SOURCES:
                run = crawl_source(SessionLocal, source, client, settings.request_delay_seconds)
                log.info("%s: %s jobs, %s new, error=%s", source.name, run.jobs_seen, run.jobs_new, run.error)
        with SessionLocal() as session:
            user_ids = list(session.scalars(select(User.id).where(User.job_description != "")))
        match_users(user_ids)
        remove_expired(SessionLocal, utcnow())
    finally:
        scrape_lock.release()
