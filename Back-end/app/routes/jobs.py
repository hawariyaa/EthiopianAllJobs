from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session as DbSession, joinedload

from .. import pipeline
from ..models import (
    LINKEDIN_SOURCE,
    THIS_WEEK_DAYS,
    CrawlRun,
    Job,
    Match,
    User,
    linkedin_listed_since,
    listed_since,
    utcnow,
)
from ..sources import SOURCES
from .deps import current_user, get_db

router = APIRouter(prefix="/api", tags=["jobs"])

LABELS = {source.name: source.label for source in SOURCES}


class JobOut(BaseModel):
    id: int
    title: str
    company: str | None
    location: str | None
    description: str
    apply_url: str
    source: str
    source_label: str
    job_type: str | None
    work_mode: str | None
    experience_level: str | None
    compensation: str | None
    published_at: datetime | None
    deadline: datetime | None
    is_closed: bool
    selected_at: datetime
    score: int
    reason: str


class JobsOut(BaseModel):
    total: int
    this_week_count: int
    past_count: int
    linkedin_count: int
    jobs: list[JobOut]


@router.get("/jobs", response_model=JobsOut)
def list_jobs(
    section: Literal["this_week", "past", "linkedin"] = "this_week",
    source: str | None = None,
    q: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
):
    now = utcnow()
    week_start = now - timedelta(days=THIS_WEEK_DAYS)
    filters = [Match.user_id == user.id, Match.is_match.is_(True)]
    if source:
        filters.append(Job.source == source)
    if q and q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(or_(Job.title.ilike(pattern, escape="\\"), Job.company.ilike(pattern, escape="\\")))

    # LinkedIn jobs have their own menu and their own two weeks; the other sites share the 21 days.
    is_linkedin = Job.source == LINKEDIN_SOURCE
    on_linkedin = and_(is_linkedin, Match.selected_at >= linkedin_listed_since(now))
    other_sites = and_(~is_linkedin, Match.selected_at >= listed_since(now))
    in_this_week = Match.selected_at >= week_start
    this_week_count, past_count, linkedin_count = db.execute(
        select(
            func.count().filter(other_sites, in_this_week),
            func.count().filter(other_sites, ~in_this_week),
            func.count().filter(on_linkedin),
        )
        .select_from(Match)
        .join(Match.job)
        .where(*filters)
    ).one()

    if section == "linkedin":
        in_section, total = on_linkedin, linkedin_count
    elif section == "this_week":
        in_section, total = and_(other_sites, in_this_week), this_week_count
    else:
        in_section, total = and_(other_sites, ~in_this_week), past_count

    closed = Job.deadline < now
    rows = db.scalars(
        select(Match)
        .join(Match.job)
        .options(joinedload(Match.job))
        .where(*filters, in_section)
        .order_by(
            case((closed, 1), else_=0),  # jobs you can still apply to come first
            func.date(Match.selected_at).desc(),
            Match.score.desc(),
            Job.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()

    def to_out(match: Match) -> JobOut:
        job = match.job
        deadline = job.deadline
        is_closed = deadline is not None and pipeline.as_utc(deadline) < now
        return JobOut(
            id=job.id, title=job.title, company=job.company, location=job.location,
            description=job.description, apply_url=job.url, source=job.source,
            source_label=LABELS.get(job.source, job.source), job_type=job.job_type,
            work_mode=job.work_mode, experience_level=job.experience_level,
            compensation=job.compensation, published_at=job.published_at, deadline=deadline,
            is_closed=is_closed, selected_at=match.selected_at, score=match.score, reason=match.reason,
        )

    return JobsOut(
        total=total,
        this_week_count=this_week_count,
        past_count=past_count,
        linkedin_count=linkedin_count,
        jobs=[to_out(match) for match in rows],
    )


@router.get("/status")
def read_status(user: User = Depends(current_user), db: DbSession = Depends(get_db)):
    sources = []
    last_updated = None
    for source in SOURCES:
        run = db.scalar(
            select(CrawlRun)
            .where(CrawlRun.source == source.name, CrawlRun.finished_at.is_not(None))
            .order_by(CrawlRun.id.desc())
            .limit(1)
        )
        if run and not run.error and (last_updated is None or run.finished_at > last_updated):
            last_updated = run.finished_at
        sources.append({"name": source.name, "label": source.label, "failed": bool(run and run.error)})
    return {
        "collecting": pipeline.scrape_lock.locked(),
        "matching": user.id in pipeline.matching_users,
        "last_updated": last_updated,
        "sources": sources,
    }
