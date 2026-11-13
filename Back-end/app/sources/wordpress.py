"""WordPress sites.

Elelana Jobs and Harmee Jobs run the WP Job Manager plugin, which publishes open jobs as JSON.
Effoysira and EthioJobsHub post each vacancy as a blog post; their JSON API is closed to robots and their
feeds are off, so we find new posts in their sitemaps and read each post's page.
"""
import re
import time
from datetime import datetime, timezone
from html import unescape
from typing import Iterator

import httpx
from bs4 import BeautifulSoup

from .base import ScrapedJob, SourceError, get_page, html_to_text, parse_datetime, parse_sitemap, request_with_retry

_CLASS_PREFIXES = {
    "types": ("job-types-", "job_listing_type-"),
    "categories": ("job-categories-", "job_listing_category-"),
}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", html or ""))).strip()


def _from_classes(classes: list[str], kind: str) -> list[str]:
    found = []
    for cls in classes:
        for prefix in _CLASS_PREFIXES[kind]:
            if cls.startswith(prefix):
                found.append(cls[len(prefix):].replace("-", " ").capitalize())
    return found


def _utc(value: str | None) -> datetime | None:
    parsed = parse_datetime(value)
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class JobManagerSource:
    PER_PAGE = 50
    MAX_PAGES = 6

    def __init__(self, name: str, label: str, base: str):
        self.name, self.label, self.base = name, label, base.rstrip("/")

    def parse_job(self, raw: dict) -> ScrapedJob:
        meta = raw.get("meta") or {}
        classes = raw.get("class_list") or []
        if isinstance(classes, dict):
            classes = list(classes.values())
        types = _from_classes(classes, "types")
        return ScrapedJob(
            external_id=str(raw["id"]),
            title=_plain(raw["title"]["rendered"]) or "Untitled job",
            url=raw["link"],
            company=(meta.get("_company_name") or "").strip() or None,
            location=(meta.get("_job_location") or "").strip() or None,
            description=html_to_text((raw.get("content") or {}).get("rendered")),
            job_type=types[0] if types else None,
            work_mode="Remote" if meta.get("_remote_position") in (1, "1", True) else None,
            compensation=(meta.get("_job_salary") or "").strip() or None,
            categories=_from_classes(classes, "categories")[:6],
            published_at=_utc(raw.get("date_gmt")),
        )

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        url = f"{self.base}/wp-json/wp/v2/job-listings"
        total_pages = 1
        page = 1
        while page <= min(total_pages, self.MAX_PAGES):
            if page > 1:
                time.sleep(delay)
            response = request_with_retry(
                client, "GET", url, params={"per_page": self.PER_PAGE, "page": page, "orderby": "date", "order": "desc"}
            )
            try:
                jobs = response.json()
                total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
            except ValueError as exc:
                raise SourceError(f"{self.label} job list is not JSON; the site may have changed") from exc
            if not isinstance(jobs, list):
                raise SourceError(f"Unexpected {self.label} job list")
            parsed = [self.parse_job(raw) for raw in jobs]
            yield from (job for job in parsed if job.published_at and job.published_at >= since)
            if any(job.published_at and job.published_at < since for job in parsed):
                return
            page += 1


class BlogPostSource:
    """Vacancy posts on a WordPress blog, found through its Yoast sitemaps."""

    MAX_POSTS = 60  # per run, so a long gap can't turn into hundreds of page loads

    def __init__(self, name: str, label: str, base: str, title_suffix: str = ""):
        self.name, self.label, self.base = name, label, base.rstrip("/")
        self.title_suffix = title_suffix

    def _recent_posts(self, client: httpx.Client, since: datetime) -> list[str]:
        index = parse_sitemap(request_with_retry(client, "GET", f"{self.base}/sitemap_index.xml").content, "sitemap")
        if not index:
            raise SourceError(f"{self.label} sitemap index is empty; the site may have changed")
        sitemaps = [loc for loc, modified in index
                    if re.search(r"/post-sitemap\d*\.xml$", loc) and (modified is None or modified >= since)]
        posts: list[tuple[datetime, str]] = []
        for sitemap in sitemaps:
            for loc, modified in parse_sitemap(request_with_retry(client, "GET", sitemap).content):
                if modified and modified >= since:
                    posts.append((modified, loc))
        posts.sort(reverse=True)
        return [url for _, url in posts[: self.MAX_POSTS]]

    def parse_post(self, html: str, url: str) -> ScrapedJob | None:
        soup = BeautifulSoup(html, "html.parser")

        def meta(prop: str) -> str:
            tag = soup.find("meta", attrs={"property": prop})
            return (tag.get("content") or "").strip() if tag else ""

        published = _utc(meta("article:published_time"))
        # Some themes have more than one content box (one may be empty); the post is the biggest.
        boxes = soup.select("div.entry-content")
        body = max(boxes, key=lambda box: len(box.get_text()), default=None)
        title = unescape(meta("og:title")) or (soup.title.string if soup.title else "")
        if self.title_suffix and title.endswith(self.title_suffix):
            title = title[: -len(self.title_suffix)]
        if not published or body is None or not title.strip():
            return None
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return ScrapedJob(
            external_id=slug[:120],
            title=title.strip()[:500],
            url=url,
            description=html_to_text(str(body)),
            location="Ethiopia",
            published_at=published,
        )

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        for url in self._recent_posts(client, since):
            time.sleep(delay)
            html = get_page(client, url)
            job = self.parse_post(html, url) if html else None
            # The sitemap date is the last edit; only posts first published since the last run are new.
            if job and job.published_at >= since:
                yield job


def wordpress_sources() -> list:
    return [
        JobManagerSource("elelanajobs", "Elelana Jobs", "https://elelanajobs.com"),
        JobManagerSource("harmeejobs", "Harmee Jobs", "https://harmeejobs.com"),
        BlogPostSource("effoysira", "Effoysira", "https://effoysira.com"),
        BlogPostSource("ethiojobshub", "EthioJobsHub", "https://ethiojobshub.com", title_suffix=" - EthioJobsHub"),
    ]
