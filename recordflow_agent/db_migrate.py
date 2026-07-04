from __future__ import annotations

import argparse
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from recordflow_agent.llm_client import load_dotenv


DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "postgres"
MIGRATION_LOCK_ID = 735214901


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str
    sql: str


@dataclass(frozen=True)
class MigrationRun:
    applied: list[str]
    skipped: list[str]


class MigrationError(RuntimeError):
    pass


def load_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    if not migrations_dir.exists():
        raise MigrationError(f"Migrations directory does not exist: {migrations_dir}")

    migrations: list[Migration] = []
    seen: set[str] = set()
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.name
        if version in seen:
            raise MigrationError(f"Duplicate migration version: {version}")
        seen.add(version)
        sql = path.read_text(encoding="utf-8")
        checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        migrations.append(Migration(version=version, path=path, checksum=checksum, sql=sql))
    return migrations


def migrate(
    database_url: str | None = None,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    dry_run: bool = False,
) -> MigrationRun:
    database_url = resolve_database_url(database_url)
    migrations = load_migrations(migrations_dir)

    import psycopg

    conn = psycopg.connect(database_url)
    conn.autocommit = True
    try:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_ID,))
        try:
            ensure_migration_table(conn)
            applied_checksums = get_applied_checksums(conn)
            plan = plan_migrations(migrations, applied_checksums)
            if dry_run:
                return plan
            pending_versions = set(plan.applied)
            for migration in migrations:
                if migration.version not in pending_versions:
                    continue
                with conn.transaction():
                    conn.execute(migration.sql)
                    conn.execute(
                        """
                        INSERT INTO schema_migrations(version, checksum)
                        VALUES (%s, %s)
                        """,
                        (migration.version, migration.checksum),
                    )
            return plan
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_ID,))
    finally:
        conn.close()


def plan_migrations(
    migrations: list[Migration],
    applied_checksums: dict[str, str],
) -> MigrationRun:
    applied: list[str] = []
    skipped: list[str] = []
    for migration in migrations:
        existing_checksum = applied_checksums.get(migration.version)
        if existing_checksum == migration.checksum:
            skipped.append(migration.version)
            continue
        if existing_checksum is not None:
            raise MigrationError(
                f"Applied migration changed: {migration.version}. "
                "Create a new migration instead of editing an applied one."
            )
        applied.append(migration.version)
    return MigrationRun(applied=applied, skipped=skipped)


def resolve_database_url(database_url: str | None = None) -> str:
    load_dotenv()
    resolved = (database_url or os.getenv("DATABASE_URL") or "").strip()
    if not resolved:
        raise MigrationError("DATABASE_URL is required.")
    if not resolved.startswith(("postgresql://", "postgres://")):
        raise MigrationError("DATABASE_URL must start with postgresql:// or postgres://.")
    return resolved


def ensure_migration_table(conn: object) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations(
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def get_applied_checksums(conn: object) -> dict[str, str]:
    rows = conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    return {row[0]: row[1] for row in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RecordFlow PostgreSQL migrations.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = migrate(
        database_url=args.database_url,
        migrations_dir=args.migrations_dir,
        dry_run=args.dry_run,
    )
    for version in result.skipped:
        print(f"skipped {version}")
    for version in result.applied:
        action = "would apply" if args.dry_run else "applied"
        print(f"{action} {version}")
    if not result.applied and not result.skipped:
        print("no migrations found")


if __name__ == "__main__":
    main()
