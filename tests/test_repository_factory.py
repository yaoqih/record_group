from pathlib import Path

from recordflow_agent.repository_factory import create_repository, default_db_path
from recordflow_agent.sqlite_repository import SQLiteRepository


def test_create_repository_uses_sqlite_when_database_url_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("RECORDFLOW_DB_PATH", str(tmp_path / "recordflow.db"))

    repo = create_repository()

    assert isinstance(repo, SQLiteRepository)
    assert repo.db_path == Path(tmp_path / "recordflow.db")
    repo.close()


def test_create_repository_uses_postgres_when_database_url_is_postgresql(monkeypatch):
    class FakePostgresRepository:
        def __init__(self, database_url: str, initialize: bool = True) -> None:
            self.database_url = database_url
            self.initialize = initialize

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/recordflow")
    monkeypatch.setattr(
        "recordflow_agent.repository_factory.PostgresRepository",
        FakePostgresRepository,
    )

    repo = create_repository(initialize=False)

    assert isinstance(repo, FakePostgresRepository)
    assert repo.database_url == "postgresql://user:pass@localhost:5432/recordflow"
    assert repo.initialize is False
