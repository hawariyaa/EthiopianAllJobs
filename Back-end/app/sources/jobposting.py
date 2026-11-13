"""Sites whose job pages carry schema.org JobPosting data (the format Google for Jobs reads):
GeezJobs and SraZone. We find new job pages, then read that data from each one."""
import json
import re
import time
from datetime import datetime
from typing import Iterator
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import ScrapedJob, SourceError, get_page, html_to_text, humanize, parse_datetime, parse_sitemap, request_with_retry


def find_job_posting(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _location(posting: dict) -> str | None:
    place = _first(posting.get("jobLocation"))
    address = place.get("address") if isinstance(place, dict) else None
    if isinstance(address, str):
        return address
    if not isinstance(address, dict):
        return None
    parts = [address.get(k) for k in ("addressLocality", "addressRegion")]
    parts = [p for p in parts if isinstance(p, str) and p.strip()]
    if parts:
        return ", ".join(dict.fromkeys(parts))
    country = address.get("addressCountry")
    return country if isinstance(country, str) else None


def job_from_posting(posting: dict, url: str, external_id: str, title_suffix: str = "") -> ScrapedJob:
    title = str(posting.get("title") or "").strip()
    if title_suffix and title.endswith(title_suffix):
        title = title[: -len(title_suffix)].strip()
    employment = _first(posting.get("employmentType"))
    organization = _first(posting.get("hiringOrganization"))
    category = posting.get("occupationCategory")
    return ScrapedJob(
        external_id=external_id[:120],
        title=title[:500] or "Untitled job",
        url=url,
        company=organization.get("name") if isinstance(organization, dict) else None,
        location=_location(posting),
        description=html_to_text(posting.get("description")),
        job_type=humanize(employment.lower()) if isinstance(employment, str) else None,
        categories=[category] if isinstance(category, str) and category else [],
        published_at=parse_datetime(posting.get("datePosted")),
        deadline=parse_datetime(posting.get("validThrough")),
    )


class GeezJobsSource:
    """New job pages come from the sitemap, which lists each one with the time it last changed."""

    name, label = "geezjobs", "GeezJobs"
    SITEMAP = "https://geezjobs.com/sitemap-detail"
    MAX_JOBS = 80

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        entries = parse_sitemap(request_with_retry(client, "GET", self.SITEMAP).content)
        if not entries:
            raise SourceError("GeezJobs sitemap is empty; the site may have changed")
        recent = [(changed, loc) for loc, changed in entries if "/job-detail/" in loc and changed and changed >= since]
        recent.sort(reverse=True)
        for _, url in recent[: self.MAX_JOBS]:
            time.sleep(delay)
            html = get_page(client, url)
            posting = find_job_posting(html) if html else None
            if posting is None:
                continue
            job = job_from_posting(posting, url, url.rstrip("/").rsplit("/", 1)[-1], title_suffix=" via GeezJobs")
            if job.published_at and job.published_at >= since:
                yield job


class SraZoneSource:
    """The job list is newest first, 12 per page, with featured jobs pinned to the top."""

    name, label = "srazone", "SraZone"
    LIST_URL = "https://srazone.et/en/jobs"
    MAX_PAGES = 8
    _JOB_LINK = re.compile(r"^/en/jobs/(?!category/|location/)[a-z0-9-]+$")

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        seen: set[str] = set()
        for page in range(1, self.MAX_PAGES + 1):
            if page > 1:
                time.sleep(delay)
            html = request_with_retry(client, "GET", self.LIST_URL, params={"page": page} if page > 1 else None).text
            links = [a["href"] for a in BeautifulSoup(html, "html.parser").find_all("a", href=self._JOB_LINK)]
            links = [link for link in dict.fromkeys(links) if link not in seen]
            if not links:
                if page == 1:
                    raise SourceError("SraZone listed no jobs; the site may have changed")
                return
            any_new = False
            for link in links:
                seen.add(link)
                time.sleep(delay)
                url = urljoin(self.LIST_URL, link)
                html = get_page(client, url)
                posting = find_job_posting(html) if html else None
                if posting is None:
                    continue
                identifier = posting.get("identifier")
                job_id = identifier.get("value") if isinstance(identifier, dict) else None
                job = job_from_posting(posting, url, str(job_id or link.rsplit("/", 1)[-1]), title_suffix=" Featured")
                if job.published_at and job.published_at >= since:
                    any_new = True
                    yield job
            # Pinned featured jobs can be old, so stop only when a whole page has nothing new.
            if not any_new:
                return
