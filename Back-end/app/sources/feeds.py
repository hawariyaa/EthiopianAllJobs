"""Sites read through their RSS job feeds: EthioNGOJobs, NGO Jobs in Africa, ReliefWeb and ETCareers."""
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Iterator

import httpx

from .base import ScrapedJob, SourceError, html_to_text, request_with_retry

_NS = {"content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/"}


def _text(item: ET.Element, path: str) -> str:
    found = item.find(path, _NS)
    return (found.text or "").strip() if found is not None else ""


def _date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_feed(xml: bytes) -> list[ET.Element]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SourceError(f"Feed is not valid XML: {exc}") from exc
    channel = root.find("channel")
    if channel is None:
        raise SourceError("Feed has no <channel>; the site may have changed")
    return channel.findall("item")


class FeedSource:
    """One RSS feed, newest first.

    paged:         WordPress feeds accept ?paged=N for older items.
    split_title:   titles look like "Job - Company - Location" (ETCareers).
    company_tag:   element holding the employer's name, if the feed has one.
    """

    def __init__(self, name: str, label: str, url: str, *, paged: bool = False, max_pages: int = 5,
                 split_title: bool = False, company_tag: str | None = None, location: str | None = None):
        self.name, self.label, self.url = name, label, url
        self.paged, self.max_pages, self.split_title = paged, max_pages, split_title
        self.company_tag, self.location = company_tag, location

    def parse_item(self, item: ET.Element) -> ScrapedJob | None:
        title, link = unescape(_text(item, "title")), _text(item, "link")
        published = _date(_text(item, "pubDate"))
        if not title or not link or published is None:
            return None  # can't be placed in This Week / Past Two Weeks without a date
        company = unescape(_text(item, self.company_tag)) if self.company_tag else ""
        location = self.location
        if self.split_title:
            parts = [p.strip() for p in title.split(" - ")]
            if len(parts) >= 3:
                title, company, location = " - ".join(parts[:-2]), parts[-2], parts[-1]
        body = _text(item, "content:encoded") or _text(item, "description")
        categories = [unescape(c.text.strip()) for c in item.findall("category") if c.text and c.text.strip()]
        return ScrapedJob(
            external_id=(_text(item, "guid") or link)[:120],
            title=title[:500],
            url=link,
            company=company or None,
            location=location,
            description=html_to_text(body),
            categories=categories[:6],
            published_at=published,
        )

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        for page in range(1, (self.max_pages if self.paged else 1) + 1):
            if page > 1:
                time.sleep(delay)
            params = {"paged": page} if page > 1 else None
            try:
                response = request_with_retry(client, "GET", self.url, params=params)
            except httpx.HTTPStatusError as exc:
                if page > 1 and exc.response.status_code == 404:
                    return  # past the last page
                raise
            items = parse_feed(response.content)
            if not items and page == 1:
                raise SourceError(f"{self.label} feed is empty; the site may have changed")
            reached_older = False
            for item in items:
                job = self.parse_item(item)
                if job is None:
                    continue
                if job.published_at >= since:
                    yield job
                else:
                    reached_older = True
            if reached_older or not items:
                return


def feed_sources() -> list[FeedSource]:
    return [
        FeedSource("ethiongojobs", "EthioNGOJobs", "https://www.ethiongojobs.com/feed/", paged=True,
                   location="Ethiopia"),
        FeedSource("ngojobsinafrica", "NGO Jobs in Africa", "https://ngojobsinafrica.com/job-location/ethiopia/feed/",
                   paged=True, location="Ethiopia"),
        # C87 is ReliefWeb's code for Ethiopia.
        FeedSource("reliefweb", "ReliefWeb", "https://reliefweb.int/jobs/rss.xml?advanced-search=%28C87%29",
                   company_tag="author", location="Ethiopia"),
        FeedSource("etcareers", "ETCareers", "https://etcareers.com/jobs.rss", split_title=True),
    ]
