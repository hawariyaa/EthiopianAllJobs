# AllJobs Ethiopia

People register, describe the jobs they want, and get a personal list. Once a day the backend collects
newly posted jobs from 15 sites, and AI (through OpenRouter) selects the ones that suit each person.
Applying always happens on the original site.

## Sites and AI requests

Each site group's new jobs go to the AI in **one request per user per day**, so a day costs 5 requests per user:

| Group | Sites |
|---|---|
| Afriwork + Ethiojobs | Afriwork, Ethiojobs |
| Ethiopian boards 1 | GeezJobs, ETCareers, Effoysira, EthioJobsHub |
| Ethiopian boards 2 | Elelana Jobs, Harmee Jobs, Maroset, SraZone |
| NGO and UN | EthioNGOJobs, NGO Jobs in Africa (Ethiopia), ReliefWeb (Ethiopia), UN Careers (Ethiopian duty stations) |
| LinkedIn | LinkedIn, through the JSearch API (needs `JSEARCH_API_KEY`) |

A group only splits into more requests past 400 new jobs (for example, catching up after several days off).
Saving a changed job description checks the last 24 hours again straight away, which is one more request per group.
Groups are set in `Back-end/app/sources/__init__.py`.

Not included: unjobs.org (its robots.txt forbids automated reading), ezega.com and ethiopianreporterjobs.com
(behind Cloudflare's bot check), and hahu.jobs (its pages carry no job data without its private API).

A selected job stays in **This Week** for 7 days, moves to **Past Two Weeks**, and is removed after 21 days.

## First-time setup

```bash
cp Back-end/.env.example Back-end/.env   # then add your OPENROUTER_API_KEY
docker compose up -d db
(cd Back-end && /usr/bin/python3 -m venv .venv && .venv/bin/pip install -r requirements.txt)
(cd Front-end && nvm use 22 && npm install && npx next build)
```

## Run

```bash
# Back end, from Back-end/. Database changes are applied on start.
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# Front end, from Front-end/, using Node 22. Run `npx next build` first after any code change.
npx next start -H 127.0.0.1 -p 3000
```

Open http://localhost:3000.

## Admin

The admin site lives in `Admin/` (its own API and web app). See [Admin/README.md](Admin/README.md).

## Daily run

The backend must be running to collect jobs. It runs at `SCRAPE_HOUR` (default 6:00, Addis Ababa time). If the
computer was off at that time, it catches up on start, going back to the last successful run, up to 7 days.

## Tests

```bash
cd Back-end && PYTHONPATH=. DATABASE_URL=sqlite:// .venv/bin/python -m pytest
```

## Before putting this on the public internet

- Serve it over HTTPS and set `COOKIE_SECURE=true`.
- Set a spending limit on the OpenRouter key: registration is open, and each user adds AI cost.
- Add password reset, which needs an email provider.
