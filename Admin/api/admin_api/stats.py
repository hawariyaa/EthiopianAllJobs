from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session as DbSession

from app.models import CrawlRun, Job, Match, Session, User, utcnow
from app.sources import SOURCES

from .auth import current_admin, get_db

router = APIRouter(prefix="/api/admin", tags=["stats"])

DAYS = 30
LABELS = {source.name: source.label for source in SOURCES}


def _count(db: DbSession, query) -> int:
    return db.scalar(query) or 0


def _series(db: DbSession, column, today: date, *where) -> list[dict]:
    """One count per day for the last 30 days (UTC), with zeros filled in."""
    first = today - timedelta(days=DAYS - 1)
    since = datetime.combine(first, datetime.min.time()).replace(tzinfo=utcnow().tzinfo)
    day = func.date(column)
    rows = db.execute(select(day, func.count()).where(column >= since, *where).group_by(day)).all()
    counts = {str(d): n for d, n in rows}
    return [
        {"date": (d := (first + timedelta(days=i)).isoformat()), "count": counts.get(d, 0)} for i in range(DAYS)
    ]


@router.get("/stats")
def stats(db: DbSession = Depends(get_db), _=Depends(current_admin)):
    now = utcnow()
    today = now.date()
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)

    users = {
        "total": _count(db, select(func.count()).select_from(User)),
        "with_description": _count(db, select(func.count()).select_from(User).where(User.job_description != "")),
        "new_7d": _count(db, select(func.count()).select_from(User).where(User.created_at >= week)),
        "new_30d": _count(db, select(func.count()).select_from(User).where(User.created_at >= month)),
        "signed_in_now": _count(
            db, select(func.count(distinct(Session.user_id))).where(Session.expires_at > now)
        ),
    }

    per_source = {
        source: {"total": total, "new_7d": new}
        for source, total, new in db.execute(
            select(Job.source, func.count(), func.count().filter(Job.first_seen_at >= week)).group_by(Job.source)
        )
    }
    jobs = {
        "total": sum(s["total"] for s in per_source.values()),
        "new_7d": sum(s["new_7d"] for s in per_source.values()),
        "by_source": [
            {"source": name, "label": LABELS.get(name, name), **per_source.get(name, {"total": 0, "new_7d": 0})}
            for name in [*LABELS, *(n for n in per_source if n not in LABELS)]
        ],
    }

    matches = {
        "checked_total": _count(db, select(func.count()).select_from(Match)),
        "checked_7d": _count(db, select(func.count()).select_from(Match).where(Match.evaluated_at >= week)),
        "selected_total": _count(db, select(func.count()).select_from(Match).where(Match.selected_at.is_not(None))),
        "selected_7d": _count(db, select(func.count()).select_from(Match).where(Match.selected_at >= week)),
        "average_score": round(
            db.scalar(select(func.avg(Match.score)).where(Match.selected_at.is_not(None))) or 0
        ),
    }

    crawl = []
    for name in LABELS:
        last = db.scalar(select(CrawlRun).where(CrawlRun.source == name).order_by(CrawlRun.started_at.desc()).limit(1))
        last_ok = db.scalar(
            select(func.max(CrawlRun.finished_at)).where(CrawlRun.source == name, CrawlRun.error.is_(None))
        )
        failed_7d = _count(
            db,
            select(func.count())
            .select_from(CrawlRun)
            .where(CrawlRun.source == name, CrawlRun.started_at >= week, CrawlRun.error.is_not(None)),
        )
        crawl.append(
            {
                "source": name,
                "label": LABELS[name],
                "last_started_at": last.started_at if last else None,
                "last_jobs_seen": last.jobs_seen if last else None,
                "last_jobs_new": last.jobs_new if last else None,
                "last_error": last.error if last else None,
                "last_success_at": last_ok,
                "failed_runs_7d": failed_7d,
            }
        )

    return {
        "generated_at": now,
        "users": users,
        "jobs": jobs,
        "matches": matches,
        "crawl": crawl,
        "series": {
            "signups": _series(db, User.created_at, today),
            "new_jobs": _series(db, Job.first_seen_at, today),
            "ai_checks": _series(db, Match.evaluated_at, today),
            "selections": _series(db, Match.selected_at, today, Match.selected_at.is_not(None)),
        },
    }
