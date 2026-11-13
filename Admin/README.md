# Admin

A separate site for running AllJobs Ethiopia. It has its own API and its own web app, and reads the same
database as the main site.

- `api/admin_api/` – FastAPI service (port 8001). Reuses Back-end's models, config and password hashing,
  so it runs with Back-end's virtualenv.
- `web/` – Next.js app (port 3001).

Pages:
- **Dashboard** – users, jobs, AI checks, selections, 30-day charts, and the health of each source.
- **Users** – every user with search and sorting, and a detail page for each: AI requests, tokens and cost,
  jobs checked and selected, account facts, what they're looking for, and their latest jobs.

AI usage comes from the `ai_calls` table, which Back-end fills in as it makes each OpenRouter request. Restart
Back-end after pulling this change; usage from before it was logged isn't available.

## Setup

```bash
# 1. Start Back-end once, or run `PYTHONPATH=. .venv/bin/alembic upgrade head` in Back-end/,
#    so the `users.is_admin` column exists.
# 2. Make an account on the main site, then make it an admin:
cd Admin/api && ../../Back-end/.venv/bin/python -m admin_api.make_admin you@example.com
#    (add --remove to take admin access away)
# 3. Install the web app
cd Admin/web && nvm use 22 && npm install && npx next build
```

## Run

```bash
# API, from Admin/api/
../../Back-end/.venv/bin/uvicorn admin_api.main:app --host 127.0.0.1 --port 8001

# Web, from Admin/web/ (Node 22). Use `npm run dev` while editing.
npx next start -H 127.0.0.1 -p 3001
```

Open http://localhost:3001 and sign in with the admin account.

Admin sessions use their own cookie (`admin_session`), last 12 hours, and are separate from the main site's login.

## Before putting this on the public internet

Keep it off the public internet if you can (for example, only reachable over a VPN). If it must be public, serve it
over HTTPS with `COOKIE_SECURE=true`, on its own domain.
