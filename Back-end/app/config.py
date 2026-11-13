from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env", extra="ignore"
    )

    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-haiku-5.5"
    database_url: str = "postgresql+psycopg://alljobs:alljobs@localhost:5433/alljobs"
    jsearch_api_key: str = ""
    # Several searches separated by "|"; each costs one request per page
    jsearch_queries: str = "linkedin jobs in Addis Ababa|linkedin jobs in Ethiopia"
    scrape_hour: int = 6
    request_delay_seconds: float = 1.5
    match_threshold: int = 60
    cookie_secure: bool = False
    session_days: int = 30


settings = Settings()
