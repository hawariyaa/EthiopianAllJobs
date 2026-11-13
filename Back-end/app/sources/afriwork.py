import time
from datetime import datetime
from typing import Iterator

import httpx

from .base import ScrapedJob, SourceError, html_to_text, humanize, parse_datetime, request_with_retry

ENDPOINT = "https://api.afriworket.com/v1/graphql"
PAGE_SIZE = 10  # fixed inside the site's query
MAX_PAGES = 1000

# The same query afriworket.com/jobs sends for a logged-out visitor.
QUERY = """
query GetAllJobs($offset: Int!, $whereCondition: jobs_bool_exp!, $orderCondition: [jobs_order_by!]) {
  jobs(order_by: $orderCondition, offset: $offset, limit: 10, where: $whereCondition) {
    id title published_at description job_type job_site deadline experience_level
    compensation_amount_cents compensation_type compensation_currency
    skill_requirements { skill { name } }
    city { name }
    sectors { sector { name } }
    entity { name }
  }
}
"""


def _end_of_day(deadline: datetime | None) -> datetime | None:
    """Afriwork stores deadlines as midnight at the start of the last day to apply."""
    return deadline.replace(hour=23, minute=59, second=59) if deadline else None


def _compensation(raw: dict) -> str | None:
    amount = raw.get("compensation_amount_cents")
    if not amount:
        return None
    text = f"{amount / 100:,.0f} {raw.get('compensation_currency') or ''}".strip()
    period = (raw.get("compensation_type") or "").lower()
    return f"{text} ({period})" if period else text


def parse_job(raw: dict) -> ScrapedJob:
    return ScrapedJob(
        external_id=raw["id"],
        title=raw["title"].strip(),
        url=f"https://afriworket.com/jobs/{raw['id']}",
        company=(raw.get("entity") or {}).get("name"),
        location=(raw.get("city") or {}).get("name"),
        description=html_to_text(raw.get("description")),
        job_type=humanize(raw.get("job_type")),
        work_mode=humanize(raw.get("job_site")),
        experience_level=humanize(raw.get("experience_level")),
        compensation=_compensation(raw),
        categories=[s["sector"]["name"] for s in raw.get("sectors") or [] if s.get("sector")],
        skills=[s["skill"]["name"] for s in raw.get("skill_requirements") or [] if s.get("skill")],
        published_at=parse_datetime(raw.get("published_at")),
        deadline=_end_of_day(parse_datetime(raw.get("deadline"))),
    )


class AfriworkSource:
    name = "afriwork"
    label = "Afriwork"

    def fetch_jobs(self, client: httpx.Client, delay: float, since: datetime) -> Iterator[ScrapedJob]:
        for page in range(MAX_PAGES):
            if page:
                time.sleep(delay)
            payload = {
                "operationName": "GetAllJobs",
                "query": QUERY,
                "variables": {
                    "offset": page * PAGE_SIZE,
                    "whereCondition": {
                        "_and": [
                            {"approval_status": {"_in": ["PUBLISHED", "REFRESHED"]}},
                            {"published_at": {"_gte": since.isoformat()}},
                        ]
                    },
                    "orderCondition": {"published_at": "desc"},
                },
            }
            body = request_with_retry(
                client, "POST", ENDPOINT, json=payload, headers={"X-HASURA-ROLE": "anonymous"}
            ).json()
            if body.get("errors"):
                raise SourceError(f"Afriwork API error: {body['errors'][0].get('message')}")
            jobs = body["data"]["jobs"]
            yield from (parse_job(raw) for raw in jobs)
            if len(jobs) < PAGE_SIZE:
                return
