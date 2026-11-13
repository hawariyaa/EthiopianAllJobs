import time
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from typing import Iterator

import httpx

from ..config import settings
from ..models import LINKEDIN_SOURCE
from .base import ScrapedJob, SourceError, html_to_text, humanize, parse_datetime, request_with_retry

HOST = "jsearch.p.rapidapi.com"
ENDPOINT = f"https://{HOST}/search-v2"  # the old /search was retired in October 2026
MAX_PAGES = 2  # per query; keeps a daily run to a few requests on the free plan


def _date_posted(since: datetime, now: datetime) -> str:
    """Narrowest JSearch window that still covers `since`."""
    age = now - since
    if age <= timedelta(days=1):
        return "today"
    if age <= timedelta(days=3):
        return "3days"
    if age <= timedelta(days=7):
        return "week"
    return "month"


def _compensation(raw: dict) -> str | None:
    low, high = raw.get("job_min_salary"), raw.get("job_max_salary")
    if not low and not high:
        return None
    amounts = " - ".join(f"{value:,.0f}" for value in (low, high) if value)
    text = f"{amounts} {raw.get('job_salary_currency') or ''}".strip()
    period = (raw.get("job_salary_period") or "").lower()
    return f"{text} ({period})" if period else text


def _linkedin_link(raw: dict) -> str | None:
    """The LinkedIn apply link, if LinkedIn is among the places this job is posted."""
    options = [{"publisher": raw.get("job_publisher"), "apply_link": raw.get("job_apply_link")}]
    options += raw.get("apply_options") or []
    for option in options:
        link = option.get("apply_link") or ""
        host = (urlparse(link).hostname or "").lower()
        if host == "linkedin.com" or host.endswith(".linkedin.com"):
            return link
    return None


def parse_job(raw: dict) -> ScrapedJob:
    location = ", ".join(part for part in (raw.get("job_city"), raw.get("job_state")) if part)
    return ScrapedJob(
        # job_uid is short and stable; job_id is now ~400 characters, too long to store.
        external_id=raw.get("job_uid") or raw["job_id"],
        title=raw["job_title"].strip(),
        url=_linkedin_link(raw) or raw.get("job_apply_link") or raw["job_google_link"],
        company=raw.get("employer_name"),
        location=location or raw.get("job_country"),
        description=html_to_text(raw.get("job_description")),
        job_type=humanize((raw.get("job_employment_type") or "").lower() or None),
        work_mode="Remote" if raw.get("job_is_remote") else None,
        compensation=_compensation(raw),
        published_at=parse_datetime(raw.get("job_posted_at_datetime_utc")),
        deadline=parse_datetime(raw.get("job_offer_expiration_datetime_utc")),
    )


class JSearchSource:
    """LinkedIn jobs, found through Google for Jobs with the JSearch API on RapidAPI.

    This is how LinkedIn listings reach us without scraping LinkedIn: Google indexes them and
    JSearch returns them as structured data. Jobs not posted on LinkedIn are dropped, since
    the other sites are covered by their own sources.
    """

    name = LINKEDIN_SOURCE
    label = "LinkedIn"

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        queries = [q.strip() for q in settings.jsearch_queries.split("|") if q.strip()]
        if not settings.jsearch_api_key or not queries:
            raise SourceError("JSearch is not configured (JSEARCH_API_KEY / JSEARCH_QUERIES)")
        headers = {"X-RapidAPI-Key": settings.jsearch_api_key, "X-RapidAPI-Host": HOST}
        window = _date_posted(since, datetime.now(timezone.utc))
        seen: set[str] = set()
        first_request = True
        for query in queries:
            cursor = None
            for _ in range(MAX_PAGES):
                if not first_request:
                    time.sleep(delay)
                first_request = False
                params = {"query": query, "date_posted": window, "country": "et"}
                if cursor:
                    params["cursor"] = cursor
                body = request_with_retry(client, "GET", ENDPOINT, params=params, headers=headers).json()
                if body.get("status") != "OK":
                    raise SourceError(f"JSearch error: {body.get('error') or body.get('status')}")
                data = body.get("data") or {}
                for raw in data.get("jobs") or []:
                    if not _linkedin_link(raw):
                        continue
                    job = parse_job(raw)
                    if job.external_id in seen:
                        continue
                    seen.add(job.external_id)
                    # Jobs without a date can't be placed in This Week / Past Two Weeks.
                    if job.published_at and job.published_at >= since:
                        yield job
                # An empty cursor means there are no more results; asking again repeats the same page.
                cursor = data.get("cursor")
                if not cursor:
                    break
