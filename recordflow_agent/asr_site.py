from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


SITE_WORKSPACE_NAME = "ASR 网站"
SITE_WORKSPACE_PROFILE = "detailed_summary"
AGREEMENT_VERSION = "v1"
PENDING_UPLOAD_DIR = Path("var") / "site_uploads" / "pending"


@dataclass(frozen=True)
class TaskCharge:
    points: int
    basis: str


def site_store_target(repo: object) -> tuple[str, str]:
    if isinstance(repo, Path):
        return ("sqlite", str(repo))
    if isinstance(repo, str):
        if repo.startswith(("postgresql://", "postgres://")):
            return ("postgres", repo)
        return ("sqlite", repo)
    database_url = getattr(repo, "database_url", None)
    if database_url:
        return ("postgres", database_url)
    db_path = getattr(repo, "db_path", None)
    if db_path:
        return ("sqlite", str(Path(db_path)))
    raise RuntimeError("The current repository does not expose DATABASE_URL or db_path.")


class ASRSiteStore:
    _schema_ready_targets: set[tuple[str, str]] = set()
    _schema_ready_lock = threading.Lock()

    def __init__(self, repo: object) -> None:
        backend, target = site_store_target(repo)
        self.backend = backend
        self.target = target
        if backend == "postgres":
            self.conn = psycopg.connect(target, row_factory=dict_row)
            self.conn.autocommit = True
        else:
            db_path = Path(target)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        self._ensure_schema_initialized()

    def close(self) -> None:
        self.conn.close()

    def next_id(self, prefix: str) -> str:
        return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            f"SELECT * FROM site_users ORDER BY created_at DESC{self._secondary_order()}"
        )
        return [self._row_dict(row) for row in rows]

    def create_user(self, name: str, role: str = "user") -> dict[str, Any]:
        user_id = self.next_id("usr")
        self._execute(
            """
            INSERT INTO site_users(id, name, role, points_balance)
            VALUES ({}, {}, {}, 0)
            """,
            (user_id, name, role),
        )
        return self.get_user(user_id)

    def update_user_name(self, user_id: str, name: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_users
            SET name = {}, updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (name, user_id),
        )
        return self.get_user(user_id)

    def get_user(self, user_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM site_users WHERE id = {}", (user_id,))
        if row is None:
            raise KeyError(user_id)
        return self._row_dict(row)

    def get_wechat_identity(self, appid: str, openid: str) -> dict[str, Any] | None:
        row = self._fetchone(
            """
            SELECT * FROM site_wechat_identities
            WHERE appid = {} AND openid = {}
            """,
            (appid, openid),
        )
        return self._row_dict(row) if row is not None else None

    def get_user_wechat_openid(self, user_id: str, appid: str) -> str | None:
        if not appid:
            return None
        row = self._fetchone(
            """
            SELECT openid FROM site_wechat_identities
            WHERE user_id = {} AND appid = {}
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, appid),
        )
        if row is None:
            return None
        return str(self._row_dict(row).get("openid") or "") or None

    def get_or_create_wechat_user(
        self,
        *,
        appid: str,
        openid: str,
        unionid: str | None,
        session_key: str,
        default_name: str = "微信用户",
        signup_points: int = 0,
    ) -> dict[str, Any]:
        identity = self.get_wechat_identity(appid, openid)
        if identity:
            self._execute(
                """
                UPDATE site_wechat_identities
                SET unionid = {}, session_key = {}, updated_at = CURRENT_TIMESTAMP
                WHERE id = {}
                """,
                (unionid or "", session_key, identity["id"]),
            )
            return self.get_user(identity["user_id"])

        user = self.create_user(default_name)
        identity_id = self.next_id("wxid")
        self._execute(
            """
            INSERT INTO site_wechat_identities(
                id, user_id, appid, openid, unionid, session_key
            )
            VALUES ({}, {}, {}, {}, {}, {})
            """,
            (identity_id, user["id"], appid, openid, unionid or "", session_key),
        )
        if signup_points > 0:
            user = self.add_points(
                user["id"],
                delta=signup_points,
                kind="signup_bonus",
                note="wechat miniapp signup bonus",
            )
        return user

    def add_points(
        self,
        user_id: str,
        *,
        delta: int,
        kind: str,
        note: str = "",
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if delta == 0:
            raise ValueError("delta must not be 0.")
        user = self.get_user(user_id)
        new_balance = int(user["points_balance"]) + delta
        if new_balance < 0:
            raise ValueError("Insufficient points.")
        ledger_id = self.next_id("ptx")
        self._execute(
            """
            UPDATE site_users
            SET points_balance = {}, updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (new_balance, user_id),
        )
        self._execute(
            """
            INSERT INTO site_point_ledger(id, user_id, delta, kind, note, task_id)
            VALUES ({}, {}, {}, {}, {}, {})
            """,
            (ledger_id, user_id, delta, kind, note, task_id),
        )
        return self.get_user(user_id)

    def list_point_ledger(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if user_id:
            rows = self._fetchall(
                f"""
                SELECT * FROM site_point_ledger
                WHERE user_id = {{}}
                ORDER BY created_at DESC{self._secondary_order()}
                """,
                (user_id,),
            )
        else:
            rows = self._fetchall(
                f"SELECT * FROM site_point_ledger ORDER BY created_at DESC{self._secondary_order()}"
            )
        return [self._row_dict(row) for row in rows]

    def create_payment_order(
        self,
        *,
        out_trade_no: str,
        user_id: str,
        points: int,
        amount_cents: int,
        provider: str = "wechatpay",
    ) -> dict[str, Any]:
        self._execute(
            """
            INSERT INTO site_payment_orders(
                out_trade_no, user_id, provider, points, amount_cents, status
            )
            VALUES ({}, {}, {}, {}, {}, 'created')
            """,
            (out_trade_no, user_id, provider, points, amount_cents),
        )
        return self.get_payment_order(out_trade_no)

    def get_payment_order(self, out_trade_no: str) -> dict[str, Any]:
        row = self._fetchone(
            "SELECT * FROM site_payment_orders WHERE out_trade_no = {}",
            (out_trade_no,),
        )
        if row is None:
            raise KeyError(out_trade_no)
        return self._row_dict(row)

    def mark_payment_order_paid(
        self,
        *,
        out_trade_no: str,
        transaction_id: str,
    ) -> tuple[dict[str, Any], bool]:
        order = self.get_payment_order(out_trade_no)
        if order["status"] == "paid":
            return order, False
        user = self.add_points(
            order["user_id"],
            delta=int(order["points"]),
            kind="wechatpay_recharge",
            note=f"wechatpay {out_trade_no}",
        )
        self._execute(
            """
            UPDATE site_payment_orders
            SET status = 'paid',
                transaction_id = {},
                paid_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE out_trade_no = {}
            """,
            (transaction_id, out_trade_no),
        )
        return user, True

    def mark_payment_order_status(
        self,
        *,
        out_trade_no: str,
        status: str,
        transaction_id: str = "",
    ) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_payment_orders
            SET status = {},
                transaction_id = COALESCE(NULLIF({}, ''), transaction_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE out_trade_no = {}
            """,
            (status, transaction_id, out_trade_no),
        )
        return self.get_payment_order(out_trade_no)

    def create_pending_task(
        self,
        *,
        task_id: str,
        user_id: str,
        workspace_id: str,
        title: str,
        source_name: str,
        content_type: str,
        original_size_bytes: int,
        duration_seconds: float,
        points_cost: int,
        charge_basis: str,
        agreement_version: str,
        local_file_path: str,
    ) -> dict[str, Any]:
        expires_clause = self._expires_in_days_clause(7)
        local_expires_clause = local_expires_in_days_clause(self.backend, 1)
        self._execute(
            f"""
            INSERT INTO site_asr_tasks(
                id, user_id, workspace_id, media_id, job_id, title, source_name,
                content_type, status, points_cost, charge_basis, agreement_version,
                editable_utterances, error, confirmed_at, expires_at,
                original_size_bytes, duration_seconds, local_file_path, local_expires_at
            )
            VALUES (
                {self._placeholders(15)},
                {expires_clause},
                {self._placeholders(3)},
                {local_expires_clause}
            )
            """,
            (
                task_id,
                user_id,
                workspace_id,
                None,
                None,
                title,
                source_name,
                content_type,
                "uploaded",
                points_cost,
                charge_basis,
                agreement_version,
                self._json_param([]),
                None,
                None,
                original_size_bytes,
                duration_seconds,
                local_file_path,
            ),
        )
        return self.get_task(task_id)

    def attach_task_media_job(self, task_id: str, media_id: str, job_id: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET media_id = {}, job_id = {}, status = 'queued', updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (media_id, job_id, task_id),
        )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM site_asr_tasks WHERE id = {}", (task_id,))
        if row is None:
            raise KeyError(task_id)
        return task_row(self._row_dict(row))

    def get_task_detail(self, task_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM site_asr_tasks WHERE id = {}", (task_id,))
        if row is None:
            raise KeyError(task_id)
        return task_detail_row(self._row_dict(row))

    def get_task_editor(self, task_id: str) -> dict[str, Any]:
        row = self._fetchone("SELECT * FROM site_asr_tasks WHERE id = {}", (task_id,))
        if row is None:
            raise KeyError(task_id)
        return task_editor_row(self._row_dict(row))

    def get_task_by_media_id(self, media_id: str) -> dict[str, Any] | None:
        row = self._fetchone("SELECT * FROM site_asr_tasks WHERE media_id = {}", (media_id,))
        return task_row(self._row_dict(row)) if row else None

    def list_user_tasks(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            f"""
            SELECT * FROM site_asr_tasks
            WHERE user_id = {{}}
            ORDER BY created_at DESC{self._secondary_order()}
            """,
            (user_id,),
        )
        return [task_summary_row(self._row_dict(row)) for row in rows]

    def list_tasks(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            f"SELECT * FROM site_asr_tasks ORDER BY created_at DESC{self._secondary_order()}"
        )
        return [task_summary_row(self._row_dict(row)) for row in rows]

    def update_task_status(
        self,
        task_id: str,
        status: str,
        *,
        error: str | None = None,
        transcript_text: str | None = None,
        raw_result: dict[str, Any] | None = None,
        local_file_path: str | None = None,
    ) -> dict[str, Any]:
        editable_utterances: list[dict[str, Any]] | None = None
        if raw_result is not None or transcript_text is not None:
            editable_utterances = build_editable_utterances(
                raw_result=raw_result,
                transcript_text=transcript_text,
            )
        self._execute(
            """
            UPDATE site_asr_tasks
            SET status = {},
                error = {},
                editable_utterances = COALESCE({}, editable_utterances),
                local_file_path = COALESCE({}, local_file_path),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (
                status,
                error,
                self._json_param(editable_utterances) if editable_utterances is not None else None,
                local_file_path,
                task_id,
            ),
        )
        return self.get_task(task_id)

    def update_task_status_by_media_id(
        self,
        media_id: str,
        status: str,
        *,
        error: str | None = None,
        transcript_text: str | None = None,
        raw_result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        task = self.get_task_by_media_id(media_id)
        if task is None:
            return None
        return self.update_task_status(
            task["id"],
            status,
            error=error,
            transcript_text=transcript_text,
            raw_result=raw_result,
        )

    def mark_task_starting(self, task_id: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET status = 'starting',
                confirmed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (task_id,),
        )
        return self.get_task(task_id)

    def save_correction(
        self,
        task_id: str,
        utterances: list[dict[str, Any]],
    ) -> dict[str, Any]:
        next_utterances = normalize_editable_utterances(utterances)
        self._execute(
            """
            UPDATE site_asr_tasks
            SET editable_utterances = {},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (
                self._json_param(next_utterances),
                task_id,
            ),
        )
        return self.get_task(task_id)

    def confirm_result(self, task_id: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET status = 'confirmed', updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (task_id,),
        )
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> dict[str, Any]:
        task = self.get_task(task_id)
        self._execute("DELETE FROM site_asr_tasks WHERE id = {}", (task_id,))
        return task

    def rename_task(self, task_id: str, title: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET title = {},
                source_name = {},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (title, title, task_id),
        )
        return self.get_task(task_id)

    def list_expired_tasks(self) -> list[dict[str, Any]]:
        rows = self._fetchall(
            f"""
            SELECT
                t.id AS task_id,
                t.media_id AS media_id,
                t.local_file_path AS local_file_path,
                m.object_name AS object_name
            FROM site_asr_tasks t
            LEFT JOIN media_records m ON m.id = t.media_id
            WHERE t.status != 'expired'
              AND (
                    t.expires_at <= CURRENT_TIMESTAMP
                    OR (t.local_file_path IS NOT NULL AND t.local_expires_at <= CURRENT_TIMESTAMP)
                  )
            ORDER BY t.created_at, t.id DESC
            """
        )
        return [self._row_dict(row) for row in rows]

    def expire_task(self, task_id: str, media_id: str | None = None) -> None:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET status = 'expired',
                error = 'Expired after 7 days.',
                local_file_path = NULL,
                local_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (task_id,),
        )
        if media_id:
            self._execute(
                """
                UPDATE media_records
                SET status = 'expired',
                    transcript_text = NULL,
                    utterances = {},
                    raw_asr_result = {},
                    error = 'Expired after 7 days.',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = {}
                """,
                (self._json_param([]), self._json_param({}), media_id),
            )

    def _execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        statement = self._format_query(query)
        self.conn.execute(statement, params)
        if self.backend == "sqlite":
            self.conn.commit()

    def _fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        return self.conn.execute(self._format_query(query), params).fetchone()

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        return self.conn.execute(self._format_query(query), params).fetchall()

    def _format_query(self, query: str) -> str:
        return query.replace("{}", "%s" if self.backend == "postgres" else "?")

    def _json_param(self, value: Any) -> Any:
        if self.backend == "postgres":
            return Jsonb(value)
        return json.dumps(value, ensure_ascii=False)

    def _row_dict(self, row: Any) -> dict[str, Any]:
        return dict(row)

    def _secondary_order(self) -> str:
        return ", id DESC"

    def _expires_in_days_clause(self, days: int) -> str:
        if self.backend == "postgres":
            return f"CURRENT_TIMESTAMP + INTERVAL '{days} days'"
        return f"datetime('now', '+{days} days')"

    def _placeholders(self, count: int) -> str:
        token = "%s" if self.backend == "postgres" else "?"
        return ", ".join([token] * count)

    def _init_schema(self) -> None:
        if self.backend == "postgres":
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_users(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    points_balance INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_point_ledger(
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    task_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_wechat_identities(
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    appid TEXT NOT NULL,
                    openid TEXT NOT NULL,
                    unionid TEXT NOT NULL DEFAULT '',
                    session_key TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(appid, openid)
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_payment_orders(
                    out_trade_no TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    points INTEGER NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    transaction_id TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    paid_at TIMESTAMPTZ
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_asr_tasks(
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    media_id TEXT,
                    job_id TEXT,
                    title TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    points_cost INTEGER NOT NULL,
                    charge_basis TEXT NOT NULL,
                    agreement_version TEXT NOT NULL,
                    editable_utterances JSONB NOT NULL DEFAULT '[]'::jsonb,
                    error TEXT,
                    confirmed_at TIMESTAMPTZ,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    original_size_bytes BIGINT NOT NULL DEFAULT 0,
                    duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0,
                    local_file_path TEXT,
                    local_expires_at TIMESTAMPTZ
                )
                """
            )
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS original_size_bytes BIGINT NOT NULL DEFAULT 0")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 0")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS local_file_path TEXT")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS local_expires_at TIMESTAMPTZ")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS editable_utterances JSONB NOT NULL DEFAULT '[]'::jsonb")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS raw_result JSONB DEFAULT '{}'::jsonb")
            self.conn.execute("UPDATE site_asr_tasks SET raw_result = '{}'::jsonb WHERE raw_result IS NULL")
            self.conn.execute("ALTER TABLE site_asr_tasks ALTER COLUMN raw_result SET DEFAULT '{}'::jsonb")
        else:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS site_users(
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    points_balance INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS site_point_ledger(
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    delta INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    task_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS site_wechat_identities(
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    appid TEXT NOT NULL,
                    openid TEXT NOT NULL,
                    unionid TEXT NOT NULL DEFAULT '',
                    session_key TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(appid, openid)
                );
                CREATE TABLE IF NOT EXISTS site_payment_orders(
                    out_trade_no TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    points INTEGER NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    transaction_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    paid_at TEXT
                );
                CREATE TABLE IF NOT EXISTS site_asr_tasks(
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    media_id TEXT,
                    job_id TEXT,
                    title TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    points_cost INTEGER NOT NULL,
                    charge_basis TEXT NOT NULL,
                    agreement_version TEXT NOT NULL,
                    editable_utterances TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    confirmed_at TEXT,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    original_size_bytes INTEGER NOT NULL DEFAULT 0,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    local_file_path TEXT,
                    local_expires_at TEXT
                );
                """
            )
            self._ensure_sqlite_column("site_asr_tasks", "original_size_bytes", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_sqlite_column("site_asr_tasks", "duration_seconds", "REAL NOT NULL DEFAULT 0")
            self._ensure_sqlite_column("site_asr_tasks", "local_file_path", "TEXT")
            self._ensure_sqlite_column("site_asr_tasks", "local_expires_at", "TEXT")
            self._ensure_sqlite_column("site_asr_tasks", "editable_utterances", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_sqlite_column("site_asr_tasks", "raw_result", "TEXT NOT NULL DEFAULT '{}'")
            self.conn.commit()

    def _ensure_sqlite_column(self, table: str, column: str, definition: str) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_schema_initialized(self) -> None:
        schema_key = (self.backend, self.target)
        if schema_key in self._schema_ready_targets:
            return
        with self._schema_ready_lock:
            if schema_key in self._schema_ready_targets:
                return
            self._init_schema()
            self._schema_ready_targets.add(schema_key)


def estimate_task_charge(duration_seconds: float) -> TaskCharge:
    points = max(1, math.ceil(max(duration_seconds, 0.0) / 60.0))
    return TaskCharge(points=points, basis=f"{duration_seconds:.1f}s -> {points} points")


def pending_upload_path(task_id: str, filename: str) -> Path:
    safe_name = Path(filename).name or "recording.bin"
    PENDING_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return PENDING_UPLOAD_DIR / f"{task_id}-{safe_name}"


def local_expires_in_days_clause(backend: str, days: int) -> str:
    if backend == "postgres":
        return f"CURRENT_TIMESTAMP + INTERVAL '{days} days'"
    return f"datetime('now', '+{days} days')"


def remove_local_file_if_exists(path: str | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def task_row(row: dict[str, Any]) -> dict[str, Any]:
    stored_utterances = row.get("editable_utterances") if isinstance(row, dict) else row["editable_utterances"]
    if isinstance(stored_utterances, str):
        stored_utterances = json.loads(stored_utterances)
    utterances = normalize_editable_utterances(stored_utterances)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "workspace_id": row["workspace_id"],
        "media_id": row["media_id"],
        "job_id": row["job_id"],
        "title": row["title"],
        "source_name": row["source_name"],
        "content_type": row["content_type"],
        "status": row["status"],
        "points_cost": row["points_cost"],
        "charge_basis": row["charge_basis"],
        "agreement_version": row["agreement_version"],
        "utterances": utterances,
        "error": row["error"],
        "confirmed_at": stringify_time(row["confirmed_at"]),
        "expires_at": stringify_time(row["expires_at"]),
        "created_at": stringify_time(row["created_at"]),
        "updated_at": stringify_time(row["updated_at"]),
        "original_size_bytes": row["original_size_bytes"],
        "duration_seconds": float(row["duration_seconds"] or 0),
        "local_file_path": row.get("local_file_path") if isinstance(row, dict) else row["local_file_path"],
        "local_expires_at": stringify_time(
            row.get("local_expires_at") if isinstance(row, dict) else row["local_expires_at"]
        ),
    }


def task_summary_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "workspace_id": row["workspace_id"],
        "media_id": row["media_id"],
        "job_id": row["job_id"],
        "title": row["title"],
        "source_name": row["source_name"],
        "content_type": row["content_type"],
        "status": row["status"],
        "points_cost": row["points_cost"],
        "charge_basis": row["charge_basis"],
        "agreement_version": row["agreement_version"],
        "error": row["error"],
        "confirmed_at": stringify_time(row["confirmed_at"]),
        "expires_at": stringify_time(row["expires_at"]),
        "created_at": stringify_time(row["created_at"]),
        "updated_at": stringify_time(row["updated_at"]),
        "original_size_bytes": row["original_size_bytes"],
        "duration_seconds": float(row["duration_seconds"] or 0),
        "local_file_path": row.get("local_file_path") if isinstance(row, dict) else row["local_file_path"],
        "local_expires_at": stringify_time(
            row.get("local_expires_at") if isinstance(row, dict) else row["local_expires_at"]
        ),
    }


def task_detail_row(row: dict[str, Any]) -> dict[str, Any]:
    return task_summary_row(row)


def task_editor_row(row: dict[str, Any]) -> dict[str, Any]:
    task = task_row(row)
    return {
        **task_summary_row(row),
        "utterances": task["utterances"],
    }


def extract_task_utterances(raw_result: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_result, dict):
        return []
    result_items = raw_result.get("result")
    utterances: list[dict[str, Any]] = []
    if isinstance(result_items, list):
        for item in result_items:
            if not isinstance(item, dict):
                continue
            item_utterances = item.get("utterances")
            if not isinstance(item_utterances, list):
                continue
            for utterance in item_utterances:
                if not isinstance(utterance, dict):
                    continue
                utterances.append(
                    {
                        "text": str(utterance.get("text") or "").strip(),
                        "start_time": int(utterance.get("start_time") or 0),
                        "end_time": int(utterance.get("end_time") or 0),
                        "words": merge_word_chunks(
                            utterance.get("words") if isinstance(utterance.get("words"), list) else []
                        ),
                    }
                )
    if utterances:
        return split_large_utterances(utterances)
    return extract_delta_utterances(raw_result)


def build_editable_utterances(
    *,
    raw_result: dict[str, Any] | None = None,
    transcript_text: str | None = None,
) -> list[dict[str, Any]]:
    utterances = extract_task_utterances(raw_result or {})
    if utterances:
        return normalize_editable_utterances(utterances)
    if transcript_text:
        return normalize_editable_utterances(
            [{"text": line, "start_time": 0, "end_time": 0, "words": []} for line in split_text_lines(transcript_text)]
        )
    return []


def split_text_lines(text: str) -> list[str]:
    return [normalize_plain_text(item) for item in text.splitlines() if normalize_plain_text(item)]


def normalize_plain_text(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def normalize_editable_utterances(utterances: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, utterance in enumerate(utterances or []):
        if not isinstance(utterance, dict):
            continue
        text = normalize_plain_text(utterance.get("text") or "")
        if not text:
            continue
        start_time = int(utterance.get("start_time") or 0)
        end_time = int(utterance.get("end_time") or start_time)
        words = normalize_word_chunks(utterance.get("words") if isinstance(utterance.get("words"), list) else [])
        normalized.append(
            {
                "id": str(utterance.get("id") or f"utt-{index}-{start_time}-{end_time}"),
                "text": text,
                "start_time": start_time,
                "end_time": end_time,
                "words": words,
            }
        )
    return normalized


def normalize_word_chunks(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        text = normalize_plain_text(word.get("text") or "")
        if not text:
            continue
        start_time = int(word.get("start_time") or 0)
        end_time = int(word.get("end_time") or start_time)
        normalized.append(
            {
                "text": text,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
    return normalized


def build_text_export(utterances: list[dict[str, Any]]) -> str:
    lines = [normalize_plain_text(utterance.get("text") or "") for utterance in utterances if isinstance(utterance, dict)]
    text = "\n".join(line for line in lines if line)
    return f"{text}\n" if text else ""


def build_srt_export(utterances: list[dict[str, Any]]) -> str:
    normalized = normalize_editable_utterances(utterances)
    blocks: list[str] = []
    cursor_ms = 0
    for index, utterance in enumerate(normalized):
        text = normalize_plain_text(utterance.get("text") or "")
        if not text:
            continue
        raw_start = int(utterance.get("start_time") or 0)
        raw_end = int(utterance.get("end_time") or raw_start)
        start_ms = max(0, raw_start)
        end_ms = max(start_ms, raw_end)
        if raw_start <= 0 and raw_end <= 0 and blocks:
            start_ms = cursor_ms
            end_ms = start_ms
        if end_ms <= start_ms:
            next_start = next_utterance_start(normalized, index)
            end_ms = next_start if next_start and next_start > start_ms else start_ms + 2000
        cursor_ms = max(cursor_ms, end_ms)
        blocks.append(
            "\n".join(
                [
                    str(len(blocks) + 1),
                    f"{format_srt_timestamp(start_ms)} --> {format_srt_timestamp(end_ms)}",
                    text,
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def next_utterance_start(utterances: list[dict[str, Any]], index: int) -> int | None:
    for utterance in utterances[index + 1 :]:
        start_time = int(utterance.get("start_time") or 0)
        if start_time > 0:
            return start_time
    return None


def format_srt_timestamp(milliseconds: int) -> str:
    total_ms = max(0, int(milliseconds))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def merge_word_chunks(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    buffer: dict[str, Any] | None = None
    for item in words:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start_time = int(item.get("start_time") or 0)
        end_time = int(item.get("end_time") or start_time)
        if buffer is None:
            buffer = {"text": text, "start_time": start_time, "end_time": end_time}
            continue
        contiguous = start_time <= int(buffer["end_time"]) + 120
        should_merge = len(text) == 1 and len(str(buffer["text"])) < 4
        if contiguous and should_merge:
            buffer["text"] = f"{buffer['text']}{text}"
            buffer["end_time"] = end_time
            continue
        merged.append(buffer)
        buffer = {"text": text, "start_time": start_time, "end_time": end_time}
    if buffer is not None:
        merged.append(buffer)
    return merged


def split_large_utterances(utterances: list[dict[str, Any]]) -> list[dict[str, Any]]:
    split_items: list[dict[str, Any]] = []
    for utterance in utterances:
        words = utterance.get("words") or []
        text = str(utterance.get("text") or "").strip()
        if not words or len(text) < 80:
            split_items.append(utterance)
            continue
        current_words: list[dict[str, Any]] = []
        current_text: list[str] = []
        current_start: int | None = None
        current_end: int | None = None
        for word in words:
            if not isinstance(word, dict):
                continue
            word_text = str(word.get("text") or "").strip()
            if not word_text:
                continue
            start_time = int(word.get("start_time") or 0)
            end_time = int(word.get("end_time") or start_time)
            if current_start is None:
                current_start = start_time
            current_end = end_time
            current_words.append(word)
            current_text.append(word_text)
            pause_break = len(current_words) >= 12 and start_time > 0 and current_end > 0 and (start_time - int(current_words[-2].get("end_time") or start_time) if len(current_words) > 1 else 0) >= 600
            punctuation_break = word_text.endswith(("。", "！", "？", "；", ".", "!", "?", ";"))
            comma_break = len(current_words) >= 8 and word_text.endswith(("，", "," , "、"))
            if punctuation_break or comma_break or pause_break:
                split_items.append(
                    {
                        "text": "".join(current_text).strip(),
                        "start_time": current_start or 0,
                        "end_time": current_end or current_start or 0,
                        "words": current_words[:],
                    }
                )
                current_words = []
                current_text = []
                current_start = None
                current_end = None
        if current_text:
            split_items.append(
                {
                    "text": "".join(current_text).strip(),
                    "start_time": current_start or 0,
                    "end_time": current_end or current_start or 0,
                    "words": current_words[:],
                }
            )
    return split_items


def extract_delta_utterances(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    events = raw_result.get("events")
    if not isinstance(events, list):
        return []
    utterances: list[dict[str, Any]] = []
    current_words: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_start: int | None = None
    current_end: int | None = None
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "transcript.text.delta":
            continue
        text = str(event.get("delta") or "").strip()
        if not text:
            continue
        start_time = int(event.get("start_time") or 0)
        end_time = int(event.get("end_time") or start_time)
        current_words.append({"text": text, "start_time": start_time, "end_time": end_time})
        current_text.append(text)
        if current_start is None:
            current_start = start_time
        current_end = end_time
        if text.endswith(("。", "！", "？", ".", "!", "?")):
            utterances.append(
                {
                    "text": "".join(current_text).strip(),
                    "start_time": current_start or 0,
                    "end_time": current_end or current_start or 0,
                    "words": current_words[:],
                }
            )
            current_words = []
            current_text = []
            current_start = None
            current_end = None
    if current_text:
        utterances.append(
            {
                "text": "".join(current_text).strip(),
                "start_time": current_start or 0,
                "end_time": current_end or current_start or 0,
                "words": current_words[:],
            }
        )
    return utterances


def stringify_time(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
