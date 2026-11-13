from ..config import settings
from .afriwork import AfriworkSource
from .apis import MarosetSource, UNCareersSource
from .base import Source
from .ethiojobs import EthiojobsSource
from .feeds import feed_sources
from .jobposting import GeezJobsSource, SraZoneSource
from .jsearch import JSearchSource
from .wordpress import wordpress_sources

# To add a site: write a class with name, label and fetch_jobs, list it here, and put it in a MATCH_GROUPS group.
SOURCES: list[Source] = [
    AfriworkSource(),
    EthiojobsSource(),
    GeezJobsSource(),
    SraZoneSource(),
    *wordpress_sources(),
    *feed_sources(),
    MarosetSource(),
    UNCareersSource(),
]

# LinkedIn jobs come through the JSearch API, so they only join the daily run once
# JSEARCH_API_KEY is set.
if settings.jsearch_api_key:
    SOURCES.append(JSearchSource())

# Each group's new jobs go to the AI in one request per user per day (see matching.match_user).
MATCH_GROUPS: dict[str, list[str]] = {
    "main": ["afriwork", "ethiojobs"],
    "ethiopia-1": ["geezjobs", "etcareers", "effoysira", "ethiojobshub"],
    "ethiopia-2": ["elelanajobs", "harmeejobs", "maroset", "srazone"],
    "ngo-un": ["ethiongojobs", "ngojobsinafrica", "reliefweb", "uncareers"],
    "linkedin": ["linkedin"],
}
GROUP_LABELS = {
    "main": "Afriwork + Ethiojobs",
    "ethiopia-1": "Ethiopian boards 1",
    "ethiopia-2": "Ethiopian boards 2",
    "ngo-un": "NGO and UN",
    "linkedin": "LinkedIn",
}
_GROUP_OF = {source: group for group, sources in MATCH_GROUPS.items() for source in sources}


def group_of(source: str) -> str:
    """Sites not in a group (e.g. in tests) share one request."""
    return _GROUP_OF.get(source, "other")
