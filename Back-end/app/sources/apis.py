"""Sites read through the public JSON their own pages load: Maroset and UN Careers."""
import ast
import re
import time
from datetime import datetime, timezone
from typing import Iterator

import httpx

from .base import ScrapedJob, SourceError, html_to_text, parse_datetime, request_with_retry


def _when(value) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class MarosetSource:
    name, label = "maroset", "Maroset"
    URL = "https://api.maroset.com/jobs/"
    PAGE = 50
    MAX_PAGES = 6

    def parse_job(self, raw: dict) -> ScrapedJob:
        return ScrapedJob(
            external_id=str(raw["id"]),
            title=(raw.get("job_title") or "Untitled job").strip(),
            url=f"https://maroset.com/jobs/{raw['id']}",
            company=raw.get("company_name"),
            description=html_to_text(raw.get("description_snippet")),
            compensation=raw.get("salary") or None,
            categories=[raw["job_field"]] if isinstance(raw.get("job_field"), str) and raw["job_field"] else [],
            location="Ethiopia",
            published_at=_when(raw.get("timestamp")),
        )

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        for page in range(self.MAX_PAGES):
            if page:
                time.sleep(delay)
            body = request_with_retry(client, "GET", self.URL, params={"skip": page * self.PAGE, "limit": self.PAGE}).json()
            if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                raise SourceError("Unexpected Maroset job list; the site may have changed")
            for raw in body["items"]:
                if raw.get("status", "active") != "active":
                    continue
                job = self.parse_job(raw)
                if job.published_at and job.published_at >= since:
                    yield job
            if not body.get("has_more"):
                return


# Duty stations in Ethiopia that UN jobs are posted to.
ETHIOPIAN_STATIONS = {
    "ADDIS ABABA", "GAMBELLA", "GAMBELA", "JIJIGA", "MEKELLE", "MEKELE", "SEMERA", "DIRE DAWA", "GONDAR",
    "BAHIR DAR", "HAWASSA", "AWASSA", "ASSOSA", "DOLO ADO", "DOLLO ADO", "SHIRE", "DESSIE", "NEKEMTE",
    "KEBRIBEYAH", "MELKADIDA", "ADAMA", "JIMMA", "ETHIOPIA",
}


def _stations(value) -> list[str]:
    # The API sometimes sends this list as a Python-style string: "[{'code': '...', 'description': '...'}]".
    if isinstance(value, str):
        try:
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return re.findall(r"'description':\s*'([^']*)'", value)
    if isinstance(value, dict):
        value = [value]
    return [str(v.get("description", "")) for v in value or [] if isinstance(v, dict)]


def _dept(value) -> str | None:
    if isinstance(value, dict):
        value = value.get("name") or value.get("description")
    return value.strip() if isinstance(value, str) and value.strip() else None


class UNCareersSource:
    name, label = "uncareers", "UN Careers"
    URL = "https://careers.un.org/api/public/opening/jo/list/filteredV2/en"
    PAGE = 100
    MAX_PAGES = 10

    def parse_job(self, raw: dict, stations: list[str]) -> ScrapedJob:
        return ScrapedJob(
            external_id=str(raw["jobId"]),
            title=(raw.get("postingTitle") or raw.get("jobTitle") or "Untitled job").strip(),
            url=f"https://careers.un.org/jobSearchDescription/{raw['jobId']}?language=en",
            company=_dept(raw.get("dept")),
            location=", ".join(s.title() for s in stations) + ", Ethiopia",
            description=html_to_text(raw.get("jobDescription")),
            experience_level=raw.get("jobLevel") if isinstance(raw.get("jobLevel"), str) else None,
            published_at=_when(raw.get("startDate")),
            deadline=_when(raw.get("endDate")),
        )

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        for page in range(self.MAX_PAGES):
            if page:
                time.sleep(delay)
            body = request_with_retry(client, "POST", self.URL, json={
                "filterConfig": {"keyword": ""},
                "pagination": {"page": page, "itemPerPage": self.PAGE, "sortBy": "startDate", "sortDirection": -1},
            }).json()
            try:
                jobs = body["data"]["list"]
            except (KeyError, TypeError) as exc:
                raise SourceError("Unexpected UN Careers job list; the site may have changed") from exc
            reached_older = False
            for raw in jobs:
                posted = _when(raw.get("startDate"))
                if posted is None:
                    continue
                if posted < since:
                    reached_older = True
                    continue
                stations = _stations(raw.get("dutyStation"))
                if any(s.upper().strip() in ETHIOPIAN_STATIONS for s in stations):
                    yield self.parse_job(raw, stations)
            if reached_older or len(jobs) < self.PAGE:
                return
