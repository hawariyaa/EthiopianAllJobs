import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI

from .config import settings
from .db import SessionLocal
from .models import utcnow
from .pipeline import daily_run, needs_catch_up
from .routes import auth, jobs, profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


@asynccontextmanager
async def lifespan(_: FastAPI):
    command.upgrade(Config(str(ALEMBIC_INI)), "head")
    scheduler = BackgroundScheduler(timezone="Africa/Addis_Ababa")
    scheduler.add_job(
        daily_run, "cron", hour=settings.scrape_hour, max_instances=1, coalesce=True, misfire_grace_time=3600
    )
    # If the computer was off at the scheduled time, catch up as soon as we start.
    if needs_catch_up(SessionLocal, utcnow()):
        scheduler.add_job(daily_run, next_run_time=utcnow())
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="AllJobs Ethiopia", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(jobs.router)
