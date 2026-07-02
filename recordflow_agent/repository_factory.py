from __future__ import annotations

import os
from pathlib import Path

from recordflow_agent.llm_client import load_dotenv
from recordflow_agent.postgres_repository import PostgresRepository
from recordflow_agent.sqlite_repository import SQLiteRepository


def create_repository(initialize: bool = True) -> SQLiteRepository | PostgresRepository:
    load_dotenv()
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must start with postgresql:// or postgres://.")
        return PostgresRepository(database_url, initialize=initialize)
    return SQLiteRepository(default_db_path())


def default_db_path() -> Path:
    return Path(os.getenv("RECORDFLOW_DB_PATH", str(Path("var") / "recordflow.db")))
