from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app.models import AiCall, Avatar, Job, Match, Session, User, utcnow
from app.sources import GROUP_LABELS, SOURCES

from .auth import current_admin, get_db
from .stats import _series

router = APIRouter(prefix="/api/admin", tags=["users"])

LABELS = {source.name: source.label for source in SOURCES}
# Requests logged before jobs were grouped by site were a title screen or a full read.
_OLD_KINDS = {"screen": "Title screen (old)", "evaluate": "Full read (old)"}


def _group_label(kind: str) -> str:
    return GROUP_LABELS.get(kind) or _OLD_KINDS.get(kind) or kind


def _ai_totals():
    return (
        select(
            AiCall.user_id.label("user_id"),
            func.count().label("calls"),
            func.coalesce(func.sum(AiCall.prompt_tokens + AiCall.completion_tokens), 0).label("tokens"),
            func.coalesce(func.sum(AiCall.cost), 0.0).label("cost"),
            func.max(AiCall.created_at).label("last_call"),
        )
        .group_by(AiCall.user_id)
        .subquery()
    )


def _match_totals():
    return (
        select(
            Match.user_id.label("user_id"),
            func.count().label("checked"),
            func.count().filter(Match.selected_at.is_not(None)).label("selected"),
        )
        .group_by(Match.user_id)
        .subquery()
    )


@router.get("/users")
def list_users(
    q: str = "",
    sort: Literal["newest", "oldest", "name", "ai_calls", "selected"] = "newest",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DbSession = Depends(get_db),
    _=Depends(current_admin),
):
    ai, mt = _ai_totals(), _match_totals()
    calls, selected = func.coalesce(ai.c.calls, 0), func.coalesce(mt.c.selected, 0)
    query = select(User, calls, func.coalesce(ai.c.tokens, 0), func.coalesce(ai.c.cost, 0.0), func.coalesce(mt.c.checked, 0), selected)
    query = query.outerjoin(ai, ai.c.user_id == User.id).outerjoin(mt, mt.c.user_id == User.id)
    count = select(func.count()).select_from(User)
    term = q.strip().lower()
    if term:
        like = f"%{term.replace('%', r'\%').replace('_', r'\_')}%"
        match = or_(func.lower(User.email).like(like, escape="\\"), func.lower(User.name).like(like, escape="\\"))
        query, count = query.where(match), count.where(match)
    order = {
        "newest": User.created_at.desc(),
        "oldest": User.created_at.asc(),
        "name": func.lower(User.name).asc(),
        "ai_calls": calls.desc(),
        "selected": selected.desc(),
    }[sort]
    rows = db.execute(query.order_by(order, User.id).limit(limit).offset(offset)).all()
    return {
        "total": db.scalar(count) or 0,
        "users": [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "is_admin": u.is_admin,
                "has_description": bool(u.job_description.strip()),
                "has_avatar": u.avatar_updated_at is not None,
                "created_at": u.created_at,
                "ai_calls": n_calls,
                "ai_tokens": int(tokens),
                "ai_cost": float(cost),
                "jobs_checked": checked,
                "jobs_selected": n_selected,
            }
            for u, n_calls, tokens, cost, checked, n_selected in rows
        ],
    }


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: DbSession = Depends(get_db), _=Depends(current_admin)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user.")
    now = utcnow()
    week, three_weeks = now - timedelta(days=7), now - timedelta(days=21)

    def matches(*where) -> int:
        return db.scalar(select(func.count()).select_from(Match).where(Match.user_id == user_id, *where)) or 0

    selected = Match.selected_at.is_not(None)
    checked = matches()
    n_selected = matches(selected)
    match_info = {
        "checked": checked,
        "selected": n_selected,
        "not_selected": checked - n_selected,
        "this_week": matches(Match.selected_at >= week),
        "past_two_weeks": matches(Match.selected_at < week, Match.selected_at >= three_weeks),
        "average_score": round(db.scalar(select(func.avg(Match.score)).where(Match.user_id == user_id, selected)) or 0),
    }

    def calls(*where):
        return select(func.count()).select_from(AiCall).where(AiCall.user_id == user_id, *where)

    totals = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(AiCall.prompt_tokens), 0),
            func.coalesce(func.sum(AiCall.completion_tokens), 0),
            func.coalesce(func.sum(AiCall.cost), 0.0),
            func.coalesce(func.sum(AiCall.attempts), 0),
            func.min(AiCall.created_at),
        ).where(AiCall.user_id == user_id)
    ).one()
    by_kind = {
        kind: n
        for kind, n in db.execute(
            select(AiCall.kind, func.count()).where(AiCall.user_id == user_id).group_by(AiCall.kind)
        )
    }
    recent_calls = db.scalars(
        select(AiCall).where(AiCall.user_id == user_id).order_by(AiCall.created_at.desc()).limit(20)
    ).all()
    ai = {
        "calls": totals[0],
        "calls_7d": db.scalar(calls(AiCall.created_at >= week)) or 0,
        "failed": db.scalar(calls(AiCall.ok.is_(False))) or 0,
        "by_group": [
            {"group": kind, "label": _group_label(kind), "calls": n}
            for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1])
        ],
        "attempts": int(totals[4]),
        "prompt_tokens": int(totals[1]),
        "completion_tokens": int(totals[2]),
        "cost": float(totals[3]),
        "tracking_since": totals[5],
        "per_day": _series(db, AiCall.created_at, now.date(), AiCall.user_id == user_id),
        "recent": [
            {
                "created_at": c.created_at,
                "kind": c.kind,
                "group_label": _group_label(c.kind),
                "model": c.model,
                "attempts": c.attempts,
                "tokens": c.prompt_tokens + c.completion_tokens,
                "cost": c.cost,
                "ok": c.ok,
                "error": c.error,
            }
            for c in recent_calls
        ],
    }

    jobs = db.execute(
        select(Match, Job)
        .join(Job, Job.id == Match.job_id)
        .where(Match.user_id == user_id, selected)
        .order_by(Match.selected_at.desc())
        .limit(25)
    ).all()

    sessions = db.scalar(select(func.count()).select_from(Session).where(Session.user_id == user_id, Session.expires_at > now)) or 0
    return {
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
            "job_description": user.job_description,
            "description_version": user.description_version,
            "matching_from": user.matching_from,
            "has_avatar": user.avatar_updated_at is not None,
            "avatar_updated_at": user.avatar_updated_at,
            "active_sessions": sessions,
        },
        "matches": match_info,
        "ai": ai,
        "selected_jobs": [
            {
                "job_id": job.id,
                "title": job.title,
                "company": job.company,
                "source": LABELS.get(job.source, job.source),
                "url": job.url,
                "score": m.score,
                "reason": m.reason,
                "selected_at": m.selected_at,
            }
            for m, job in jobs
        ],
    }


@router.get("/users/{user_id}/avatar")
def user_avatar(user_id: int, db: DbSession = Depends(get_db), _=Depends(current_admin)):
    avatar = db.get(Avatar, user_id)
    if avatar is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No picture.")
    return Response(avatar.image, media_type="image/webp",
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )
