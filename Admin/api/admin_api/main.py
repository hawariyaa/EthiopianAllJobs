from fastapi import FastAPI

from . import auth, stats, users

# Back-end owns the database schema and applies migrations when it starts, so run Back-end
# at least once after pulling a new migration.
app = FastAPI(title="AllJobs Ethiopia Admin", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth.router)
app.include_router(stats.router)
app.include_router(users.router)
