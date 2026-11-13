import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Protocol

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "AllJobsEthiopia-personal/0.1"
RETRY_STATUSES = {429, 500, 502, 503, 504}
_BLOCK_TAGS = ["p", "div", "br", "li", "tr", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"]


class SourceError(RuntimeError):
    """The site answered, but not in the shape we expect (it may have changed)."""


@dataclass
class ScrapedJob:
    external_id: str
    title: str
    url: str
    company: str | None = None
    location: str | None = None
    description: str = ""
    job_type: str | None = None
    work_mode: str | None = None
    experience_level: str | None = None
    compensation: str | None = None
    categories: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    deadline: datetime | None = None


class Source(Protocol):
    name: str
    label: str

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        """Yield jobs posted at or after `since`. Raise SourceError if the site looks changed."""
        ...


def request_with_retry(client: httpx.Client, method: str, url: str, **kwargs) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(4):
        if attempt:
            time.sleep(2**attempt)
        try:
            response = client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            last_error = exc
            continue
        if response.status_code in RETRY_STATUSES:
            last_error = SourceError(f"{url} returned HTTP {response.status_code}")
            continue
        response.raise_for_status()
        return response
    raise SourceError(f"{url} failed after retries: {last_error}")


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all("li"):
        tag.insert(0, "• ")
    for tag in soup.find_all("td"):
        tag.insert_after(" ")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_after("\n")
    text = soup.get_text().replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def humanize(value: str | None) -> str | None:
    """FULL_TIME -> Full time"""
    return value.replace("_", " ").capitalize() if value else None


def parse_sitemap(xml: bytes, entry: str = "url") -> list[tuple[str, datetime | None]]:
    """(loc, lastmod) for each <url> (or <sitemap>) in a sitemap, whatever its namespace."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SourceError(f"Sitemap is not valid XML: {exc}") from exc
    found = []
    for node in root:
        if node.tag.rsplit("}", 1)[-1] != entry:
            continue
        values = {child.tag.rsplit("}", 1)[-1]: (child.text or "").strip() for child in node}
        if values.get("loc"):
            modified = parse_datetime(values.get("lastmod"))
            if modified and modified.tzinfo is None:
                modified = modified.replace(tzinfo=timezone.utc)
            found.append((values["loc"], modified))
    return found


def get_page(client: httpx.Client, url: str) -> str | None:
    """A single job's page; None if it has been taken down, so one dead link doesn't stop a whole site."""
    try:
        return request_with_retry(client, "GET", url).text
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (404, 410):
            return None
        raise
