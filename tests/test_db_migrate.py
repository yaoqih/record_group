import hashlib

import pytest

from recordflow_agent.db_migrate import (
    Migration,
    MigrationError,
    load_migrations,
    plan_migrations,
    resolve_database_url,
)


def test_load_migrations_orders_sql_files_and_hashes(tmp_path):
    later = tmp_path / "0002_later.sql"
    first = tmp_path / "0001_first.sql"
    later.write_text("SELECT 2;\n", encoding="utf-8")
    first.write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignored\n", encoding="utf-8")

    migrations = load_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [
        "0001_first.sql",
        "0002_later.sql",
    ]
    assert migrations[0].checksum == hashlib.sha256(b"SELECT 1;\n").hexdigest()


def test_plan_migrations_rejects_changed_applied_migration(tmp_path):
    migration = Migration(
        version="0001_initial.sql",
        path=tmp_path / "0001_initial.sql",
        checksum="new-checksum",
        sql="SELECT 1;",
    )

    with pytest.raises(MigrationError, match="Applied migration changed"):
        plan_migrations([migration], {"0001_initial.sql": "old-checksum"})


def test_plan_migrations_returns_pending_and_skipped(tmp_path):
    applied = Migration(
        version="0001_initial.sql",
        path=tmp_path / "0001_initial.sql",
        checksum="same",
        sql="SELECT 1;",
    )
    pending = Migration(
        version="0002_next.sql",
        path=tmp_path / "0002_next.sql",
        checksum="next",
        sql="SELECT 2;",
    )

    plan = plan_migrations([applied, pending], {"0001_initial.sql": "same"})

    assert plan.skipped == ["0001_initial.sql"]
    assert plan.applied == ["0002_next.sql"]


def test_resolve_database_url_requires_postgres(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///recordflow.db")

    with pytest.raises(MigrationError, match="postgresql:// or postgres://"):
        resolve_database_url()
