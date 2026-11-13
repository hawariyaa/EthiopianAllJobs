import json
from datetime import datetime, timezone

import httpx
import pytest

from app.sources import MATCH_GROUPS, SOURCES, group_of
from app.sources.apis import MarosetSource, UNCareersSource, _stations
from app.sources.base import SourceError, parse_sitemap
from app.sources.feeds import FeedSource
from app.sources.jobposting import GeezJobsSource, SraZoneSource, find_job_posting, job_from_posting
from app.sources.wordpress import BlogPostSource, JobManagerSource

SINCE = datetime(2026, 11, 10, tzinfo=timezone.utc)


def client_for(routes: dict):
    """routes: {url-without-query or (url, query-param value): response body or httpx.Response}"""
    seen = []

    def handler(request: httpx.Request):
        seen.append(str(request.url))
        key = str(request.url.copy_with(query=None))
        page = request.url.params.get("paged") or request.url.params.get("page")
        body = routes.get((key, page), routes.get(key))
        if body is None:
            return httpx.Response(404)
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, (dict, list)):
            return httpx.Response(200, json=body)
        return httpx.Response(200, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_every_site_is_in_exactly_one_group():
    names = [s.name for s in SOURCES] + ["linkedin"]
    grouped = [name for group in MATCH_GROUPS.values() for name in group]
    assert sorted(set(names)) == sorted(grouped)
    assert len(grouped) == len(set(grouped)) == 15
    assert group_of("afriwork") == group_of("ethiojobs") == "main"
    assert group_of("unknown") == "other"


# ---- RSS feeds

def rss(*items):
    return ('<?xml version="1.0"?><rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>'
            + "".join(items) + "</channel></rss>")


def item(title, date, link="https://x.test/1", guid="g1", body="<p>Do it</p>", extra=""):
    return (f"<item><title>{title}</title><link>{link}</link><guid>{guid}</guid><pubDate>{date}</pubDate>"
            f"<content:encoded><![CDATA[{body}]]></content:encoded>{extra}</item>")


def test_feed_splits_titles_and_keeps_only_new_items():
    feed = rss(
        item("Nurse - Amref Health Africa - Addis Ababa, Ethiopia", "Wed, 11 Nov 2026 13:34:47 -0600", guid="n1"),
        item("Old - Acme - Adama", "Mon, 09 Nov 2026 10:00:00 +0000", guid="o1"),
        item("No date", "", guid="x"),
    )
    client, _ = client_for({"https://etcareers.com/jobs.rss": feed})
    source = FeedSource("etcareers", "ETCareers", "https://etcareers.com/jobs.rss", split_title=True)
    jobs = list(source.fetch_jobs(client, 0, SINCE))
    assert [(j.title, j.company, j.location, j.external_id) for j in jobs] == [
        ("Nurse", "Amref Health Africa", "Addis Ababa, Ethiopia", "n1")
    ]
    assert jobs[0].description == "Do it"


def test_wordpress_feed_reads_older_pages_until_it_reaches_old_items():
    url = "https://www.ethiongojobs.com/feed/"
    client, seen = client_for({
        (url, None): rss(item("A", "Wed, 11 Nov 2026 10:00:00 +0000", guid="a")),
        (url, "2"): rss(item("B", "Tue, 10 Nov 2026 10:00:00 +0000", guid="b"),
                        item("C", "Sun, 08 Nov 2026 10:00:00 +0000", guid="c")),
        (url, "3"): rss(item("D", "Sat, 07 Nov 2026 10:00:00 +0000", guid="d")),
    })
    source = FeedSource("ethiongojobs", "EthioNGOJobs", url, paged=True, location="Ethiopia")
    assert [j.title for j in source.fetch_jobs(client, 0, SINCE)] == ["A", "B"]
    assert len(seen) == 2  # page 3 is never needed


def test_feed_author_is_the_employer_and_empty_feed_is_an_error():
    feed = rss(item("Officer", "Wed, 11 Nov 2026 10:00:00 +0000", extra="<author>Norwegian Refugee Council</author>"))
    client, _ = client_for({"https://reliefweb.int/jobs/rss.xml": feed})
    source = FeedSource("reliefweb", "ReliefWeb", "https://reliefweb.int/jobs/rss.xml", company_tag="author")
    assert next(source.fetch_jobs(client, 0, SINCE)).company == "Norwegian Refugee Council"
    client, _ = client_for({"https://reliefweb.int/jobs/rss.xml": rss()})
    with pytest.raises(SourceError, match="empty"):
        list(source.fetch_jobs(client, 0, SINCE))


# ---- WordPress

def test_job_manager_reads_listings():
    raw = {
        "id": 56141, "date_gmt": "2026-11-10T16:40:46", "link": "https://harmeejobs.com/job/logistics-officer/",
        "title": {"rendered": "Logistics &amp; Supply Officer"}, "content": {"rendered": "<p>Plan routes</p>"},
        "meta": {"_job_location": "Adama", "_company_name": "Acme", "_remote_position": 0},
        "class_list": ["job_listing", "job-types-full-time", "job-categories-ngo-jobs"],
    }
    old = dict(raw, id=1, date_gmt="2026-11-01T00:00:00")
    client, _ = client_for({"https://harmeejobs.com/wp-json/wp/v2/job-listings": httpx.Response(
        200, json=[raw, old], headers={"X-WP-TotalPages": "3"})})
    jobs = list(JobManagerSource("harmeejobs", "Harmee Jobs", "https://harmeejobs.com").fetch_jobs(client, 0, SINCE))
    assert len(jobs) == 1  # stops at the old one; pages 2-3 aren't read
    job = jobs[0]
    assert (job.external_id, job.title, job.company, job.location) == ("56141", "Logistics & Supply Officer", "Acme", "Adama")
    assert (job.job_type, job.categories, job.description) == ("Full time", ["Ngo jobs"], "Plan routes")
    assert job.published_at == datetime(2026, 11, 10, 16, 40, 46, tzinfo=timezone.utc)


SITEMAP_INDEX = """<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://blog.test/post-sitemap.xml</loc><lastmod>2026-01-01T00:00:00+00:00</lastmod></sitemap>
<sitemap><loc>https://blog.test/post-sitemap2.xml</loc><lastmod>2026-11-11T17:52:04+00:00</lastmod></sitemap>
<sitemap><loc>https://blog.test/page-sitemap.xml</loc><lastmod>2026-11-11T17:52:04+00:00</lastmod></sitemap>
</sitemapindex>"""
POSTS = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://blog.test/bank-vacancy/</loc><lastmod>2026-11-11T13:57:40+00:00</lastmod></url>
<url><loc>https://blog.test/edited-old-post/</loc><lastmod>2026-11-11T09:00:00+00:00</lastmod></url>
<url><loc>https://blog.test/gone/</loc><lastmod>2026-11-11T08:00:00+00:00</lastmod></url>
<url><loc>https://blog.test/ancient/</loc><lastmod>2026-10-01T00:00:00+00:00</lastmod></url>
</urlset>"""


def post(title, published):
    return (f'<html><head><meta property="og:title" content="{title} - EthioJobsHub">'
            f'<meta property="article:published_time" content="{published}"></head><body>'
            '<div class="entry-content"></div><div class="entry-content single-content"><p>Apply by Friday</p></div>'
            "</body></html>")


def test_blog_posts_come_from_the_sitemap_and_skip_old_and_missing_posts():
    client, seen = client_for({
        "https://blog.test/sitemap_index.xml": SITEMAP_INDEX,
        "https://blog.test/post-sitemap2.xml": POSTS,
        "https://blog.test/bank-vacancy/": post("Bank Vacancy", "2026-11-11T13:50:00+00:00"),
        "https://blog.test/edited-old-post/": post("Old Post", "2026-09-01T00:00:00+00:00"),
    })
    source = BlogPostSource("ethiojobshub", "EthioJobsHub", "https://blog.test", title_suffix=" - EthioJobsHub")
    jobs = list(source.fetch_jobs(client, 0, SINCE))
    assert [(j.external_id, j.title, j.description) for j in jobs] == [("bank-vacancy", "Bank Vacancy", "Apply by Friday")]
    assert "https://blog.test/post-sitemap.xml" not in seen  # unchanged since the last run
    assert "https://blog.test/ancient/" not in seen


# ---- JobPosting pages

def posting_page(**fields):
    data = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Prevention Officer via GeezJobs",
            "datePosted": "2026-11-11T08:10:00+00:00", "validThrough": "2026-11-21T00:00:00+00:00",
            "employmentType": ["FULL_TIME"], "description": "<p>Run the clinic</p>",
            "hiringOrganization": {"@type": "Organization", "name": "Hamlin Fistula Ethiopia"},
            "jobLocation": {"@type": "Place", "address": {"addressLocality": "Addis Ababa", "addressRegion": "Addis Ababa"}},
            **fields}
    return f'<html><script type="application/ld+json">{json.dumps(data)}</script></html>'


def test_job_posting_data_is_read_from_a_page():
    job = job_from_posting(find_job_posting(posting_page()), "https://g.test/x", "x", title_suffix=" via GeezJobs")
    assert (job.title, job.company, job.location, job.job_type) == (
        "Prevention Officer", "Hamlin Fistula Ethiopia", "Addis Ababa", "Full time")
    assert job.description == "Run the clinic" and job.deadline.day == 21
    assert find_job_posting("<html>no data</html>") is None


def test_geezjobs_reads_recently_changed_job_pages():
    sitemap = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://geezjobs.com/job-detail/prevention-officer</loc><lastmod>2026-11-11T08:10:00+00:00</lastmod></url>
    <url><loc>https://geezjobs.com/job-detail/old-job</loc><lastmod>2026-10-01T00:00:00+00:00</lastmod></url>
    <url><loc>https://geezjobs.com/article/tips</loc><lastmod>2026-11-11T00:00:00+00:00</lastmod></url>
    </urlset>"""
    client, seen = client_for({
        GeezJobsSource.SITEMAP: sitemap,
        "https://geezjobs.com/job-detail/prevention-officer": posting_page(),
    })
    jobs = list(GeezJobsSource().fetch_jobs(client, 0, SINCE))
    assert [j.external_id for j in jobs] == ["prevention-officer"]
    assert len(seen) == 2


def test_srazone_skips_dead_links_and_stops_at_a_page_with_nothing_new():
    listing = lambda *slugs: "".join(f'<a href="/en/jobs/{s}">x</a>' for s in slugs) + '<a href="/en/jobs/category/it">IT</a>'
    base = "https://srazone.et/en/jobs"
    client, seen = client_for({
        (base, None): listing("new-job-aaa", "dead-link-bbb"),
        (base, "2"): listing("old-job-ccc"),
        (base, "3"): listing("never-read"),
        f"{base}/new-job-aaa": posting_page(title="Engineer Featured", identifier={"value": "uuid-1"}),
        f"{base}/old-job-ccc": posting_page(datePosted="2026-10-01T00:00:00Z"),
    })
    jobs = list(SraZoneSource().fetch_jobs(client, 0, SINCE))
    assert [(j.external_id, j.title) for j in jobs] == [("uuid-1", "Engineer")]
    assert not any("never-read" in url for url in seen)


# ---- APIs

def test_maroset_reads_active_jobs():
    body = {"items": [
        {"id": "u1", "job_title": "Backend Developer", "company_name": "Private employer", "description_snippet": "Build APIs",
         "job_field": "Tech", "salary": "negotiable", "status": "active", "timestamp": "2026-11-10T21:46:24"},
        {"id": "u2", "job_title": "Closed", "status": "closed", "timestamp": "2026-11-10T21:46:24"},
    ], "has_more": False}
    client, _ = client_for({MarosetSource.URL: body})
    jobs = list(MarosetSource().fetch_jobs(client, 0, SINCE))
    assert [(j.title, j.url, j.categories) for j in jobs] == [("Backend Developer", "https://maroset.com/jobs/u1", ["Tech"])]


def test_un_careers_keeps_only_new_jobs_in_ethiopia():
    def job(job_id, station, start):
        return {"jobId": job_id, "postingTitle": f"Job {job_id}", "dept": "Economic Commission for Africa",
                "dutyStation": str([{"code": "1", "description": station}]), "jobDescription": "<p>Advise</p>",
                "jobLevel": "P-3", "startDate": start, "endDate": "2026-12-01T00:00:00.000Z"}
    body = {"data": {"list": [
        job("1", "ADDIS ABABA", "2026-11-11T05:00:00.000Z"),
        job("2", "NAIROBI", "2026-11-11T05:00:00.000Z"),
        job("3", "GAMBELLA", "2026-11-01T05:00:00.000Z"),
    ], "count": 3}}
    client, seen = client_for({UNCareersSource.URL: body})
    jobs = list(UNCareersSource().fetch_jobs(client, 0, SINCE))
    assert [(j.external_id, j.location, j.experience_level) for j in jobs] == [("1", "Addis Ababa, Ethiopia", "P-3")]
    assert len(seen) == 1
    assert _stations([{"description": "JIJIGA"}]) == ["JIJIGA"]


def test_sitemaps_are_read_whatever_their_namespace():
    plain = "<urlset><url><loc>https://a.test/1</loc></url></urlset>"
    assert parse_sitemap(plain.encode()) == [("https://a.test/1", None)]
    with pytest.raises(SourceError):
        parse_sitemap(b"<html>not a sitemap")
