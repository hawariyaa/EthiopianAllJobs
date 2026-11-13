import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import matching, pipeline, security
from app.main import app
from app.matching import match_user, parse_json_reply
from app.models import Avatar, Base, CrawlRun, Job, Match, Session, User, utcnow
from app.pipeline import crawl_since, crawl_source, needs_catch_up, remove_expired
from app.routes import deps, profile
from app.sources import afriwork, ethiojobs, jsearch
from app.sources.base import ScrapedJob, SourceError, html_to_text

SINCE = datetime(2026, 11, 4, tzinfo=timezone.utc)


@pytest.fixture
def factory():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def started(monkeypatch):
    calls = []
    monkeypatch.setattr(profile.pipeline, "start_matching_user", calls.append)
    return calls


@pytest.fixture
def client(factory, started):
    def db():
        with factory() as session:
            yield session

    app.dependency_overrides[deps.get_db] = db
    security._failures.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


def scraped(external_id="a", title="Backend Engineer", description="Python work"):
    return ScrapedJob(external_id=external_id, title=title, url=f"https://x.test/{external_id}", description=description)


class FakeSource:
    name, label = "fake", "Fake"

    def __init__(self, jobs=(), error=None):
        self.jobs, self.error, self.since = jobs, error, None

    def fetch_jobs(self, client, delay, since):
        self.since = since
        yield from self.jobs
        if self.error:
            raise self.error


class FakeLLM:
    """Lists jobs whose line contains `keep`: score 90, or 30 if the title has 'Junior'."""

    def __init__(self, keep="Engineer", fail=False):
        self.keep, self.fail, self.calls = keep, fail, []

    def complete_json(self, system, user, max_tokens, kind="match"):
        self.calls.append((kind, user))
        if self.fail:
            raise RuntimeError("down")
        matches = [
            {"id": int(line.split("|")[0][3:]), "score": 30 if "Junior" in line else 90, "reason": " fits\nyou "}
            for line in user.splitlines()
            if line.startswith("id=") and self.keep in line
        ]
        return {"matches": matches + [{"id": 99999, "score": 99, "reason": "unknown ids are ignored"}]}


def add_user(factory, description="software jobs", email="a@example.com", **fields):
    with factory() as s:
        user = User(email=email, name="A", password_hash="x", job_description=description,
                    matching_from=utcnow() - timedelta(hours=24), **fields)
        s.add(user)
        s.commit()
        return user.id


def add_job(factory, external_id="a", title="Backend Engineer", first_seen=None, source="fake", **fields):
    with factory() as s:
        job = Job(source=source, external_id=external_id, title=title, url=f"https://x.test/{external_id}",
                  first_seen_at=first_seen or utcnow(), **fields)
        s.add(job)
        s.commit()
        return job.id


def add_selected(factory, user_id, job_id, days_ago, version=1):
    with factory() as s:
        when = utcnow() - timedelta(days=days_ago)
        s.add(Match(user_id=user_id, job_id=job_id, description_version=version, is_match=True, score=90,
                    reason="fits", evaluated_at=when, selected_at=when))
        s.commit()


def verdicts(factory, user_id):
    with factory() as s:
        return {m.job.external_id: m for m in s.scalars(select(Match).where(Match.user_id == user_id))}


def register(client, email="me@example.com", password="correct horse"):
    return client.post("/api/auth/register", json={"name": "Me", "email": email, "password": password})


def png_bytes(size=(600, 300)):
    out = io.BytesIO()
    Image.new("RGB", size, "red").save(out, "PNG")
    return out.getvalue()


# ---- scrapers

def test_html_to_text_keeps_structure():
    text = html_to_text("<p><strong>Hi</strong> there</p><ul><li>One</li><li>Two&nbsp;x</li></ul><script>bad()</script>")
    assert text == "Hi there\n• One\n• Two x"


def test_afriwork_parse_job():
    job = afriwork.parse_job(
        {
            "id": "abc", "title": " Dev ", "description": "<p>Code</p>", "job_type": "FULL_TIME", "job_site": "ONSITE",
            "experience_level": "SENIOR", "deadline": "2026-11-11T00:00:00+00:00", "published_at": None,
            "compensation_amount_cents": 5000000, "compensation_currency": "ETB", "compensation_type": "MONTHLY",
            "entity": {"name": "Acme"}, "city": None,
            "sectors": [{"sector": {"name": "IT"}}], "skill_requirements": [{"skill": {"name": "Go"}}],
        }
    )
    assert job.url == "https://afriworket.com/jobs/abc"
    assert (job.title, job.company, job.location, job.description) == ("Dev", "Acme", None, "Code")
    assert (job.job_type, job.compensation, job.categories, job.skills) == ("Full time", "50,000 ETB (monthly)", ["IT"], ["Go"])
    assert job.deadline == datetime(2026, 11, 11, 23, 59, 59, tzinfo=timezone.utc)


def test_ethiojobs_parses_page_and_uses_stable_id():
    payload = {"props": {"pageProps": {"jobs": {"meta": {"lastPage": 95}, "data": [
        {"id": "encrypted", "slug": "AhFv-some-title", "title": "Dev", "description": "<p>x</p>", "state": "Addis Ababa",
         "location_type": "Office", "company": {"name": "Acme"}, "catalogs": [{"name": "IT"}],
         "date_published": "2026-11-05T06:55:57.000000Z", "date_expiry": "2026-11-19T23:59:59.000000Z"}
    ]}}}}
    jobs, last = ethiojobs.parse_listing_page(f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>')
    job = ethiojobs.parse_job(jobs[0])
    assert last == 95
    assert (job.external_id, job.url) == ("AhFv", "https://ethiojobs.net/job/AhFv-some-title")
    assert job.deadline == datetime(2026, 11, 19, 23, 59, 59, tzinfo=timezone.utc)


def test_ethiojobs_changed_page_is_an_error():
    with pytest.raises(SourceError):
        ethiojobs.parse_listing_page("<html>new design</html>")


def test_afriwork_api_error_is_raised():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"errors": [{"message": "denied"}]}))
    with httpx.Client(transport=transport) as client, pytest.raises(SourceError, match="denied"):
        list(afriwork.AfriworkSource().fetch_jobs(client, 0, SINCE))


def _ethiojobs_page(dates, last_page=95):
    data = [{"slug": f"id{d}-t", "title": "T", "date_published": d} for d in dates]
    payload = {"props": {"pageProps": {"jobs": {"meta": {"lastPage": last_page}, "data": data}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


def test_ethiojobs_stops_at_first_page_past_cutoff():
    new, older = "2026-11-05T06:00:00Z", "2026-11-03T06:00:00Z"
    pages = {"1": _ethiojobs_page([new]), "2": _ethiojobs_page([new, older]), "3": _ethiojobs_page([new])}
    requested = []

    def handler(request):
        requested.append(request.url.params["page"])
        return httpx.Response(200, text=pages[request.url.params["page"]])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = list(ethiojobs.EthiojobsSource().fetch_jobs(client, 0, SINCE))
    assert requested == ["1", "2"]
    assert len(jobs) == 2


def test_ethiojobs_empty_listing_is_an_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=_ethiojobs_page([])))
    with httpx.Client(transport=transport) as client, pytest.raises(SourceError):
        list(ethiojobs.EthiojobsSource().fetch_jobs(client, 0, SINCE))


def test_afriwork_asks_only_for_recent_jobs():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"jobs": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert list(afriwork.AfriworkSource().fetch_jobs(client, 0, SINCE)) == []
    assert {"published_at": {"_gte": SINCE.isoformat()}} in sent[0]["variables"]["whereCondition"]["_and"]


def _jsearch_job(job_id, posted, **extra):
    return {
        "job_uid": job_id, "job_id": f"long-google-id-for-{job_id}", "job_title": " Accountant ", "employer_name": "Acme",
        "job_apply_link": f"https://www.linkedin.com/jobs/view/{job_id}",
        "job_google_link": "https://google.com/g", "job_description": "<p>Do books</p>",
        "job_city": "Addis Ababa", "job_state": None, "job_country": "ET",
        "job_employment_type": "FULLTIME", "job_posted_at_datetime_utc": posted, **extra,
    }


@pytest.fixture
def jsearch_configured(monkeypatch):
    monkeypatch.setattr(jsearch.settings, "jsearch_api_key", "key")
    monkeypatch.setattr(jsearch.settings, "jsearch_queries", "jobs in Addis Ababa|jobs in Ethiopia")


def test_jsearch_parse_job():
    job = jsearch.parse_job(
        _jsearch_job("x1", "2026-11-05T06:00:00.000Z", job_min_salary=100, job_max_salary=200,
                     job_salary_currency="ETB", job_salary_period="MONTH")
    )
    assert (job.external_id, job.title, job.company) == ("x1", "Accountant", "Acme")
    assert job.url == "https://www.linkedin.com/jobs/view/x1"
    assert (job.location, job.job_type, job.description) == ("Addis Ababa", "Fulltime", "Do books")
    assert job.compensation == "100 - 200 ETB (month)"
    assert job.published_at == datetime(2026, 11, 5, 6, tzinfo=timezone.utc)


def test_jsearch_keeps_recent_dated_jobs_and_drops_duplicates(jsearch_configured):
    new, older = "2026-11-05T06:00:00Z", "2026-11-03T06:00:00Z"
    jobs = [_jsearch_job("a", new), _jsearch_job("b", older), _jsearch_job("c", None)]
    body = {"status": "OK", "data": {"jobs": jobs, "cursor": ""}}
    sent = []

    def handler(request):
        sent.append(dict(request.url.params))
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = list(jsearch.JSearchSource().fetch_jobs(client, 0, SINCE))
    assert [job.external_id for job in jobs] == ["a"]  # b is too old, c has no date, query 2 repeats a
    assert (jsearch.JSearchSource.name, jsearch.JSearchSource.label) == ("linkedin", "LinkedIn")
    assert [p["query"] for p in sent] == ["jobs in Addis Ababa", "jobs in Ethiopia"]  # no cursor: one request each
    assert sent[0]["country"] == "et" and "cursor" not in sent[0]


def test_jsearch_follows_the_cursor_up_to_two_pages(jsearch_configured, monkeypatch):
    monkeypatch.setattr(jsearch.settings, "jsearch_queries", "jobs")
    posted = "2026-11-05T06:00:00Z"
    pages = {
        None: {"jobs": [_jsearch_job("p1", posted)], "cursor": "c2"},
        "c2": {"jobs": [_jsearch_job("p2", posted)], "cursor": "c3"},
        "c3": {"jobs": [_jsearch_job("p3", posted)], "cursor": ""},
    }
    requested = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        requested.append(cursor)
        return httpx.Response(200, json={"status": "OK", "data": pages[cursor]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs = list(jsearch.JSearchSource().fetch_jobs(client, 0, SINCE))
    assert requested == [None, "c2"]  # stops at MAX_PAGES
    assert [job.external_id for job in jobs] == ["p1", "p2"]
    assert jsearch.ENDPOINT.endswith("/search-v2")


def test_jsearch_keeps_only_jobs_posted_on_linkedin(jsearch_configured, monkeypatch):
    monkeypatch.setattr(jsearch.settings, "jsearch_queries", "jobs")
    posted = "2026-11-05T06:00:00Z"
    elsewhere = _jsearch_job("web", posted, job_apply_link="https://acme.test/careers/1")
    also_linkedin = _jsearch_job(
        "also", posted, job_apply_link="https://acme.test/careers/2",
        apply_options=[{"publisher": "LinkedIn", "apply_link": "https://et.linkedin.com/jobs/view/2"}],
    )
    lookalike = _jsearch_job("fake", posted, job_apply_link="https://notlinkedin.com/jobs/3")
    body = {"status": "OK", "data": {"jobs": [_jsearch_job("a", posted), elsewhere, also_linkedin, lookalike]}}
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    with httpx.Client(transport=transport) as client:
        jobs = list(jsearch.JSearchSource().fetch_jobs(client, 0, SINCE))
    assert {job.external_id: job.url for job in jobs} == {
        "a": "https://www.linkedin.com/jobs/view/a",
        "also": "https://et.linkedin.com/jobs/view/2",
    }


def test_jsearch_api_error_is_raised(jsearch_configured):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ERROR", "error": "quota"}))
    with httpx.Client(transport=transport) as client, pytest.raises(SourceError, match="quota"):
        list(jsearch.JSearchSource().fetch_jobs(client, 0, SINCE))


def test_jsearch_without_a_key_is_an_error(monkeypatch):
    monkeypatch.setattr(jsearch.settings, "jsearch_api_key", "")
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        with pytest.raises(SourceError, match="not configured"):
            list(jsearch.JSearchSource().fetch_jobs(client, 0, SINCE))



# ---- daily collection

def test_crawl_keeps_jobs_it_no_longer_sees(factory):
    crawl_source(factory, FakeSource([scraped("a"), scraped("b")]), None, 0)
    run = crawl_source(factory, FakeSource([scraped("a")]), None, 0)
    with factory() as s:
        assert {j.external_id for j in s.scalars(select(Job))} == {"a", "b"}
    assert (run.jobs_seen, run.jobs_new, run.error) == (1, 0, None)


def test_failed_crawl_records_error(factory):
    run = crawl_source(factory, FakeSource([], SourceError("broke")), None, 0)
    assert run.error and run.finished_at


def test_first_crawl_covers_past_24_hours(factory):
    source = FakeSource([scraped()])
    before = utcnow()
    crawl_source(factory, source, None, 0)
    assert before - timedelta(hours=24) <= source.since <= utcnow() - timedelta(hours=24)


def test_crawl_goes_back_to_last_success_after_missed_runs(factory):
    now = utcnow()
    with factory() as s:
        s.add(CrawlRun(source="fake", started_at=now - timedelta(days=3), finished_at=now - timedelta(days=3)))
        s.add(CrawlRun(source="fake", started_at=now - timedelta(days=1), finished_at=now, error="broke"))
        s.commit()
        assert crawl_since(s, "fake", now) == now - timedelta(days=3)


def test_catch_up_is_capped_at_a_week(factory):
    now = utcnow()
    with factory() as s:
        s.add(CrawlRun(source="fake", started_at=now - timedelta(days=30), finished_at=now - timedelta(days=30)))
        s.commit()
        assert crawl_since(s, "fake", now) == now - timedelta(days=7)


def test_needs_catch_up(factory, monkeypatch):
    monkeypatch.setattr(pipeline, "SOURCES", [FakeSource()])
    now = utcnow()
    assert needs_catch_up(factory, now)
    with factory() as s:
        s.add(CrawlRun(source="fake", started_at=now - timedelta(hours=2), finished_at=now))
        s.commit()
    assert not needs_catch_up(factory, now)
    assert needs_catch_up(factory, now + timedelta(hours=23))


# ---- AI selection

def test_selects_for_each_user_separately_and_never_pays_twice(factory):
    a = add_user(factory)
    b = add_user(factory, email="b@example.com")
    add_job(factory, "eng")
    add_job(factory, "acc", "Accountant")
    add_job(factory, "jun", "Junior Engineer")

    llm = FakeLLM()
    stats = match_user(factory, llm, a, 60)
    assert (stats.checked, stats.matched, stats.requests) == (3, 1, 1)
    got = verdicts(factory, a)
    assert {k: (m.is_match, m.score, m.reason) for k, m in got.items()} == {
        "eng": (True, 90, "fits you"), "acc": (False, 0, ""), "jun": (False, 30, "fits you"),
    }
    assert got["eng"].selected_at and not got["acc"].selected_at
    assert verdicts(factory, b) == {}

    llm.calls.clear()
    match_user(factory, llm, a, 60)
    assert llm.calls == []
    match_user(factory, FakeLLM("Accountant"), b, 60)
    assert verdicts(factory, b)["acc"].is_match is True


def test_jobs_collected_before_matching_from_are_ignored(factory):
    user = add_user(factory)
    add_job(factory, "old", first_seen=utcnow() - timedelta(hours=30))
    add_job(factory, "new", first_seen=utcnow() - timedelta(hours=2))
    match_user(factory, FakeLLM(), user, 60)
    assert set(verdicts(factory, user)) == {"new"}


def test_changed_description_keeps_selected_and_rechecks_rejected(factory):
    user = add_user(factory)
    add_job(factory, "eng")
    add_job(factory, "acc", "Accountant")
    match_user(factory, FakeLLM(), user, 60)
    selected_at = verdicts(factory, user)["eng"].selected_at

    with factory() as s:
        s.get(User, user).description_version = 2
        s.commit()
    llm = FakeLLM("Accountant")
    stats = match_user(factory, llm, user, 60)
    assert stats.checked == 1  # only the rejected job, not the selected one
    got = verdicts(factory, user)
    assert got["eng"].is_match and got["eng"].selected_at == selected_at
    assert got["acc"].is_match


def test_failed_request_stays_pending_and_blank_description_costs_nothing(factory):
    blank = add_user(factory, description="", email="blank@example.com")
    user = add_user(factory)
    add_job(factory)
    llm = FakeLLM(fail=True)
    assert match_user(factory, llm, blank, 60).requests == 0
    assert llm.calls == []
    stats = match_user(factory, llm, user, 60)
    assert (stats.failed_requests, stats.checked) == (1, 0)
    assert verdicts(factory, user) == {}
    assert match_user(factory, FakeLLM(), user, 60).matched == 1


def test_one_request_per_site_group(factory):
    user = add_user(factory)
    for i, source in enumerate(["afriwork", "ethiojobs", "geezjobs", "srazone", "reliefweb", "linkedin", "fake"]):
        add_job(factory, f"j{i}", source=source)
    llm = FakeLLM()
    stats = match_user(factory, llm, user, 60)
    assert sorted(kind for kind, _ in llm.calls) == ["ethiopia-1", "ethiopia-2", "linkedin", "main", "ngo-un", "other"]
    main = next(user_text for kind, user_text in llm.calls if kind == "main")
    assert main.count("id=") == 2  # Afriwork and Ethiojobs together
    assert (stats.requests, stats.checked, stats.matched) == (6, 7, 7)


def test_a_very_large_group_is_split(factory, monkeypatch):
    monkeypatch.setattr(matching, "MAX_JOBS_PER_REQUEST", 2)
    user = add_user(factory)
    for i in range(3):
        add_job(factory, f"j{i}", source="afriwork")
    llm = FakeLLM()
    assert match_user(factory, llm, user, 60).requests == 2


def test_each_job_is_sent_short(factory):
    user = add_user(factory)
    add_job(factory, "long", description="word " * 1000, company="Acme", location="Addis Ababa")
    llm = FakeLLM()
    match_user(factory, llm, user, 60)
    sent = llm.calls[0][1]
    assert "Backend Engineer | Acme | Addis Ababa" in sent
    assert len(sent.split("Listings:\n", 1)[1]) < matching.SNIPPET_CHARS + 100


def test_parse_json_reply_handles_code_fences():
    assert parse_json_reply('```json\n{"relevant": [1]}\n```') == {"relevant": [1]}


# ---- what stays listed

def test_remove_expired(factory):
    user = add_user(factory)
    long_ago = utcnow() - timedelta(days=30)
    fresh = add_job(factory, "fresh", first_seen=long_ago)
    gone = add_job(factory, "gone", first_seen=long_ago)
    add_selected(factory, user, fresh, 20)
    add_selected(factory, user, gone, 22)
    with factory() as s:
        s.add(Session(token_hash="old", user_id=user, expires_at=utcnow() - timedelta(days=1)))
        s.commit()
    remove_expired(factory, utcnow())
    with factory() as s:
        assert {j.external_id for j in s.scalars(select(Job))} == {"fresh"}
        assert s.get(Session, "old") is None
    assert set(verdicts(factory, user)) == {"fresh"}


def test_sections_by_age_and_closed_jobs_sort_last(client, factory):
    me = register(client).json()["id"]
    now = utcnow()
    for name, days, deadline in [
        ("day6", 6.9, None), ("closed", 0.5, now - timedelta(days=1)), ("open", 1, now + timedelta(days=5)),
        ("day8", 7.1, None), ("day20", 20.9, None), ("day22", 21.1, None),
    ]:
        add_selected(factory, me, add_job(factory, name, name, deadline=deadline), days)

    week = client.get("/api/jobs?section=this_week").json()
    assert [j["title"] for j in week["jobs"]] == ["open", "day6", "closed"]
    assert [j["is_closed"] for j in week["jobs"]] == [False, False, True]
    assert (week["total"], week["this_week_count"], week["past_count"]) == (3, 3, 2)

    past = client.get("/api/jobs?section=past").json()
    assert {j["title"] for j in past["jobs"]} == {"day8", "day20"}
    assert past["total"] == 2


def test_linkedin_jobs_have_their_own_menu_for_two_weeks(client, factory):
    me = register(client).json()["id"]
    for name, days, source in [
        ("li-new", 1, "linkedin"), ("li-old", 13.9, "linkedin"), ("li-gone", 14.1, "linkedin"),
        ("site-new", 1, "fake"), ("site-past", 10, "fake"),
    ]:
        add_selected(factory, me, add_job(factory, name, name, source=source), days)

    linkedin = client.get("/api/jobs?section=linkedin").json()
    assert {j["title"] for j in linkedin["jobs"]} == {"li-new", "li-old"}
    assert linkedin["total"] == linkedin["linkedin_count"] == 2
    week = client.get("/api/jobs?section=this_week").json()
    assert [j["title"] for j in week["jobs"]] == ["site-new"]
    past = client.get("/api/jobs?section=past").json()
    assert [j["title"] for j in past["jobs"]] == ["site-past"]
    assert (week["this_week_count"], week["past_count"], week["linkedin_count"]) == (1, 1, 2)


def test_remove_expired_drops_linkedin_matches_after_two_weeks(factory):
    user = add_user(factory)
    keep = add_job(factory, "keep", source="linkedin")
    drop = add_job(factory, "drop", source="linkedin")
    site = add_job(factory, "site", source="fake")
    add_selected(factory, user, keep, 13)
    add_selected(factory, user, drop, 15)
    add_selected(factory, user, site, 15)
    remove_expired(factory, utcnow())
    assert set(verdicts(factory, user)) == {"keep", "site"}


def test_users_only_see_their_own_jobs(client, factory):
    other = add_user(factory)
    add_selected(factory, other, add_job(factory), 1)
    register(client)
    assert client.get("/api/jobs").json()["jobs"] == []


def test_rejected_jobs_are_not_listed_and_search_escapes_wildcards(client, factory):
    me = register(client).json()["id"]
    add_selected(factory, me, add_job(factory, "a", "Backend Engineer"), 1)
    with factory() as s:
        s.add(Match(user_id=me, job_id=add_job(factory, "b", "Accountant"), description_version=1, is_match=False))
        s.commit()
    assert [j["title"] for j in client.get("/api/jobs").json()["jobs"]] == ["Backend Engineer"]
    assert client.get("/api/jobs", params={"q": "backend"}).json()["total"] == 1
    assert client.get("/api/jobs", params={"q": "%"}).json()["total"] == 0


# ---- accounts

@pytest.mark.parametrize("path", ["/api/jobs", "/api/status", "/api/auth/me", "/api/profile/avatar"])
def test_logged_out_requests_are_refused(client, path):
    assert client.get(path).status_code == 401


def test_register_login_logout(client, factory):
    response = register(client, "Me@Example.com")
    assert response.status_code == 201
    assert "password_hash" not in response.json()
    assert client.get("/api/auth/me").json()["email"] == "me@example.com"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    with factory() as s:
        assert s.scalar(select(User)).password_hash.startswith("$argon2")
        assert response.cookies["session"] not in s.scalar(select(Session)).token_hash

    assert register(client, "me@example.com").status_code == 409
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    wrong = client.post("/api/auth/login", json={"email": "me@example.com", "password": "nope nope"})
    assert wrong.status_code == 401
    assert client.post("/api/auth/login", json={"email": "ME@example.com", "password": "correct horse"}).status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_old_cookie_is_useless_after_logout(client):
    token = register(client).cookies["session"]
    client.post("/api/auth/logout")
    client.cookies.set("session", token)
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize("body", [
    {"name": "Me", "email": "nope", "password": "correct horse"},
    {"name": "Me", "email": "me@example.com", "password": "short"},
    {"name": "   ", "email": "me@example.com", "password": "correct horse"},
])
def test_bad_registration_is_rejected(client, body):
    assert client.post("/api/auth/register", json=body).status_code == 422


def test_repeated_failed_logins_are_limited(client):
    register(client)
    body = {"email": "me@example.com", "password": "wrong wrong"}
    for _ in range(security.MAX_FAILURES):
        assert client.post("/api/auth/login", json=body).status_code == 401
    good = {"email": "me@example.com", "password": "correct horse"}
    assert client.post("/api/auth/login", json=good).status_code == 429


def test_change_password_logs_out_everywhere(client):
    register(client)
    bad = client.put("/api/profile/password", json={"current_password": "wrong", "new_password": "new password"})
    assert bad.status_code == 400
    ok = client.put("/api/profile/password", json={"current_password": "correct horse", "new_password": "new password"})
    assert ok.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/login", json={"email": "me@example.com", "password": "new password"}).status_code == 200


# ---- profile

def test_saving_description_starts_matching_only_when_it_changes(client, factory, started):
    me = register(client).json()["id"]
    save = lambda text, name="Me": client.put("/api/profile", json={"name": name, "job_description": text})
    assert save("  IT jobs ").json()["job_description"] == "IT jobs"
    assert started == [me]
    with factory() as s:
        user = s.get(User, me)
        version = user.description_version
        assert pipeline.as_utc(user.matching_from) <= utcnow() - timedelta(hours=23)

    assert save("IT jobs", "New Name").json()["name"] == "New Name"
    assert started == [me]
    save("")
    assert started == [me]
    with factory() as s:
        assert s.get(User, me).description_version == version + 1


def test_avatar_is_cleaned_cropped_and_private(client, factory):
    me = register(client).json()["id"]
    upload = client.put("/api/profile/avatar", files={"file": ("a.png", png_bytes(), "image/png")})
    assert upload.status_code == 200 and upload.json()["avatar_updated_at"]

    served = client.get("/api/profile/avatar")
    assert served.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(served.content)).size == (256, 256)

    assert client.delete("/api/profile/avatar").json()["avatar_updated_at"] is None
    assert client.get("/api/profile/avatar").status_code == 404
    with factory() as s:
        assert s.get(Avatar, me) is None


@pytest.mark.parametrize("name,data", [
    ("a.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("a.png", b"not an image"),
])
def test_non_images_are_rejected_as_avatars(client, name, data):
    register(client)
    assert client.put("/api/profile/avatar", files={"file": (name, data, "image/png")}).status_code == 400


def test_oversized_avatar_is_rejected(client):
    register(client)
    big = b"x" * (profile.MAX_AVATAR_BYTES + 1)
    assert client.put("/api/profile/avatar", files={"file": ("a.png", big, "image/png")}).status_code == 413
