from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.paths import DEFAULT_DB_PATH


class AdminSettings(BaseSettings):
    admin_token: str | None = None
    db_path: str = DEFAULT_DB_PATH
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    cors_origins: list[str] = ["*"]
    jwt_secret: str = ""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
