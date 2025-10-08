# Load settings from environment; expose `config` for legacy imports.
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Example: postgresql+psycopg://user:pass@host:5432/dbname
    PG_CONN_STR: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Back-compat alias used by some legacy modules
config: Settings = get_settings()
