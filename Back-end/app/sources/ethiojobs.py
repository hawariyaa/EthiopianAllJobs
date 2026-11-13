import json
import re
import time
from datetime import datetime
from typing import Iterator

import httpx

from .base import ScrapedJob, SourceError, html_to_text, parse_datetime, request_with_retry

LIST_URL = "https://ethiojobs.net/jobs"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def parse_listing_page(html: str) -> tuple[list[dict], int]:
    """Return a page's raw jobs and the last page number from its embedded data."""
    found = _NEXT_DATA.search(html)
    if not found:
        raise SourceError("Ethiojobs page has no __NEXT_DATA__; the site may have changed")
    try:
        jobs = json.loads(found.group(1))["props"]["pageProps"]["jobs"]
        return jobs["data"], int(jobs["meta"]["lastPage"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError(f"Unexpected Ethiojobs page data: {exc!r}") from exc


def parse_job(raw: dict) -> ScrapedJob:
    slug = raw["slug"]
    return ScrapedJob(
        # `id` is encrypted and changes between requests; the slug's first part is stable.
        external_id=slug.split("-", 1)[0],
        title=raw["title"].strip(),
        url=f"https://ethiojobs.net/job/{slug}",
        company=(raw.get("company") or {}).get("name"),
        location=raw.get("state"),
        description=html_to_text(raw.get("description")),
        work_mode=raw.get("location_type"),
        categories=[c["name"] for c in raw.get("catalogs") or [] if c.get("name")],
        published_at=parse_datetime(raw.get("date_published")),
        deadline=parse_datetime(raw.get("date_expiry")),
    )


class EthiojobsSource:
    name = "ethiojobs"
    label = "Ethiojobs"

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        page, last_page = 1, 1
        while page <= last_page:
            if page > 1:
                time.sleep(delay)
            # Reads public pages; robots.txt disallows /api/*, so we don't call it.
            html = request_with_retry(client, "GET", LIST_URL, params={"page": page}).text
            jobs, last_page = parse_listing_page(html)
            if not jobs and page == 1:
                raise SourceError("Ethiojobs listed no jobs at all; the site may have changed")
            parsed = [parse_job(raw) for raw in jobs]
            yield from (job for job in parsed if job.published_at and job.published_at >= since)
            # The list is newest first, so a page reaching past the cutoff is the last we need.
            if any(job.published_at and job.published_at < since for job in parsed):
                return
            page += 1
