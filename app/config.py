from functools import lru_cache
from os import environ, getenv
from pathlib import Path


def load_env_file() -> None:
    env_file = Path(__file__).resolve().parents[1] / ".env"

    if not env_file.exists():
        return

    for line in env_file.read_text().splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and getenv(key) is None:
            environ[key] = value


class Settings:
    def __init__(self) -> None:
        self.app_name = "Divine Reesha API"
        self.api_version = "0.1.0"
        self.mongodb_uri = getenv("MONGODB_URI", "mongodb://localhost:27017")
        self.mongodb_database = getenv("MONGODB_DATABASE", "divine_reesha")
        self.cors_origins = [
            origin.strip()
            for origin in getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    load_env_file()
    return Settings()
