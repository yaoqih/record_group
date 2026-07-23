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
from typing import Any, Callable, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


SITE_WORKSPACE_NAME = "ASR 网站"
SITE_WORKSPACE_PROFILE = "detailed_summary"
AGREEMENT_VERSION = "v2"
SITE_USER_ROLES = frozenset({"user", "admin"})
PENDING_UPLOAD_DIR = Path("var") / "site_uploads" / "pending"
T = TypeVar("T")

TASK_SUMMARY_COLUMNS = (
    "id",
    "user_id",
    "workspace_id",
    "media_id",
    "job_id",
    "title",
    "source_name",
    "content_type",
    "status",
    "points_cost",
    "charge_basis",
    "agreement_version",
    "notify_on_complete",
    "notification_template_id",
    "notification_job_id",
    "notification_status",
    "notification_attempts",
    "notification_last_error",
    "notification_sent_at",
    "error",
    "confirmed_at",
    "completed_at",
    "expires_at",
    "created_at",
    "updated_at",
    "original_size_bytes",
    "duration_seconds",
    "local_file_path",
    "local_expires_at",
)

MEDIA_SUMMARY_COLUMNS = (
    "id",
    "source_name",
    "stored_name",
    "url",
    "public_url",
    "content_type",
    "status",
    "created_at",
    "updated_at",
)


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
        if role not in SITE_USER_ROLES:
            raise ValueError("role must be user or admin.")
        user_id = self.next_id("usr")
        self._execute(
            """
            INSERT INTO site_users(id, name, role, points_balance)
            VALUES ({}, {}, {}, 0)
            """,
            (user_id, name, role),
        )
        return self.get_user(user_id)

    def update_user(self, user_id: str, name: str, role: str) -> dict[str, Any]:
        if role not in SITE_USER_ROLES:
            raise ValueError("role must be user or admin.")
        self._execute(
            """
            UPDATE site_users
            SET name = {}, role = {}, updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (name, role, user_id),
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

    def accept_user_agreement(
        self,
        user_id: str,
        agreement_version: str = AGREEMENT_VERSION,
        client: str = "unknown",
    ) -> dict[str, Any]:
        """Record first acceptance of the combined user agreement and privacy notice."""
        agreement_version = agreement_version.strip()
        client = client.strip() or "unknown"
        if not agreement_version:
            raise ValueError("agreement_version must not be empty.")
        self.get_user(user_id)
        self._execute(
            """
            INSERT INTO site_user_agreements(
                user_id, agreement_version, accepted_at, client
            )
            VALUES ({}, {}, CURRENT_TIMESTAMP, {})
            ON CONFLICT(user_id, agreement_version) DO NOTHING
            """,
            (user_id, agreement_version, client),
        )
        row = self._fetchone(
            """
            SELECT user_id, agreement_version, accepted_at, client
            FROM site_user_agreements
            WHERE user_id = {} AND agreement_version = {}
            """,
            (user_id, agreement_version),
        )
        if row is None:
            raise RuntimeError("Failed to persist user agreement acceptance.")
        return user_agreement_row(self._row_dict(row))

    def has_accepted_user_agreement(
        self,
        user_id: str,
        agreement_version: str = AGREEMENT_VERSION,
    ) -> bool:
        agreement_version = agreement_version.strip()
        if not agreement_version:
            return False
        row = self._fetchone(
            """
            SELECT 1
            FROM site_user_agreements
            WHERE user_id = {} AND agreement_version = {}
            """,
            (user_id, agreement_version),
        )
        return row is not None

    def list_user_agreements(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if user_id is None:
            rows = self._fetchall(
                """
                SELECT user_id, agreement_version, accepted_at, client
                FROM site_user_agreements
                ORDER BY accepted_at DESC, user_id, agreement_version DESC
                """
            )
        else:
            rows = self._fetchall(
                """
                SELECT user_id, agreement_version, accepted_at, client
                FROM site_user_agreements
                WHERE user_id = {}
                ORDER BY accepted_at DESC, agreement_version DESC
                """,
                (user_id,),
            )
        return [user_agreement_row(self._row_dict(row)) for row in rows]

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

    def get_user_wechat_identity(self, user_id: str, appid: str) -> dict[str, Any] | None:
        if not appid:
            return None
        row = self._fetchone(
            """
            SELECT * FROM site_wechat_identities
            WHERE user_id = {} AND appid = {}
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (user_id, appid),
        )
        return self._row_dict(row) if row is not None else None

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
        return self._run_atomic(
            lambda: self._apply_points_without_commit(
                user_id=user_id,
                delta=delta,
                kind=kind,
                note=note,
                task_id=task_id,
            )
        )

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

    def list_point_ledger_page(
        self,
        user_id: str,
        *,
        limit: int,
        cursor_created_at: str | None = None,
        cursor_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        conditions = ["user_id = {}"]
        params: list[Any] = [user_id]
        if cursor_created_at and cursor_id:
            conditions.append("(created_at < {} OR (created_at = {} AND id < {}))")
            params.extend([cursor_created_at, cursor_created_at, cursor_id])
        params.append(limit + 1)
        rows = self._fetchall(
            f"""
            SELECT * FROM site_point_ledger
            WHERE {' AND '.join(conditions)}
            ORDER BY created_at DESC, id DESC
            LIMIT {{}}
            """,
            tuple(params),
        )
        has_more = len(rows) > limit
        return [self._row_dict(row) for row in rows[:limit]], has_more

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
        def mark_paid() -> tuple[dict[str, Any], bool]:
            lock_clause = " FOR UPDATE" if self.backend == "postgres" else ""
            row = self.conn.execute(
                self._format_query(
                    "SELECT * FROM site_payment_orders WHERE out_trade_no = {}" + lock_clause
                ),
                (out_trade_no,),
            ).fetchone()
            if row is None:
                raise KeyError(out_trade_no)
            order = self._row_dict(row)
            if order["status"] == "paid":
                return self.get_user(order["user_id"]), False
            user = self._apply_points_without_commit(
                user_id=order["user_id"],
                delta=int(order["points"]),
                kind="wechatpay_recharge",
                note=f"wechatpay {out_trade_no}",
                task_id=None,
            )
            self.conn.execute(
                self._format_query(
                    """
                    UPDATE site_payment_orders
                    SET status = 'paid',
                        transaction_id = {},
                        paid_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE out_trade_no = {} AND status != 'paid'
                    """
                ),
                (transaction_id, out_trade_no),
            )
            return user, True

        return self._run_atomic(mark_paid)

    def _apply_points_without_commit(
        self,
        *,
        user_id: str,
        delta: int,
        kind: str,
        note: str,
        task_id: str | None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            self._format_query(
                """
                UPDATE site_users
                SET points_balance = points_balance + {},
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = {} AND points_balance + {} >= 0
                RETURNING *
                """
            ),
            (delta, user_id, delta),
        ).fetchone()
        if row is None:
            exists = self.conn.execute(
                self._format_query("SELECT 1 FROM site_users WHERE id = {}"),
                (user_id,),
            ).fetchone()
            if exists is None:
                raise KeyError(user_id)
            raise ValueError("Insufficient points.")
        self.conn.execute(
            self._format_query(
                """
                INSERT INTO site_point_ledger(id, user_id, delta, kind, note, task_id)
                VALUES ({}, {}, {}, {}, {}, {})
                """
            ),
            (self.next_id("ptx"), user_id, delta, kind, note, task_id),
        )
        return self._row_dict(row)

    def _run_atomic(self, operation: Callable[[], T]) -> T:
        if self.backend == "postgres":
            with self.conn.transaction():
                return operation()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
            self.conn.commit()
            return result
        except Exception:
            self.conn.rollback()
            raise

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

    def list_user_tasks(
        self,
        user_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be greater than 0.")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to 0.")

        params: list[Any] = [user_id]
        pagination = ""
        if limit is not None:
            pagination = " LIMIT {} OFFSET {}"
            params.extend((limit, offset))
        elif offset:
            pagination = " OFFSET {}" if self.backend == "postgres" else " LIMIT -1 OFFSET {}"
            params.append(offset)

        task_columns = ", ".join(f"t.{column} AS {column}" for column in TASK_SUMMARY_COLUMNS)
        media_columns = ", ".join(
            f"m.{column} AS media_summary_{column}" for column in MEDIA_SUMMARY_COLUMNS
        )
        rows = self._fetchall(
            f"""
            SELECT {task_columns}, {media_columns}
            FROM site_asr_tasks AS t
            LEFT JOIN media_records AS m ON m.id = t.media_id
            WHERE t.user_id = {{}}
            ORDER BY t.created_at DESC, t.id DESC{pagination}
            """,
            tuple(params),
        )
        return [task_summary_with_media_row(self._row_dict(row)) for row in rows]

    def list_user_task_statuses(self, user_id: str) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT id, status, updated_at, error
            FROM site_asr_tasks
            WHERE user_id = {}
            ORDER BY created_at DESC, id DESC
            """,
            (user_id,),
        )
        statuses: list[dict[str, Any]] = []
        for row in rows:
            row_dict = self._row_dict(row)
            statuses.append(
                {
                    "id": row_dict["id"],
                    "status": row_dict["status"],
                    "updated_at": stringify_time(row_dict["updated_at"]),
                    "error": row_dict["error"],
                }
            )
        return statuses

    def list_tasks(self) -> list[dict[str, Any]]:
        task_columns = ", ".join(f"t.{column} AS {column}" for column in TASK_SUMMARY_COLUMNS)
        rows = self._fetchall(
            f"""
            SELECT {task_columns}
            FROM site_asr_tasks AS t
            ORDER BY t.created_at DESC, t.id DESC
            """
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
                completed_at = CASE
                    WHEN {} = 'completed' THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                    ELSE completed_at
                END,
                error = {},
                editable_utterances = COALESCE({}, editable_utterances),
                local_file_path = COALESCE({}, local_file_path),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {}
            """,
            (
                status,
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

    def fail_task_with_points_refund(
        self,
        task_id: str,
        error: str,
        *,
        status: str = "failed",
    ) -> dict[str, Any]:
        """Atomically terminate a charged task and refund its consumed points once."""

        if status not in {"failed", "expired"}:
            raise ValueError(f"Task failure status {status} is not supported.")

        def fail_and_refund() -> dict[str, Any]:
            lock_clause = " FOR UPDATE" if self.backend == "postgres" else ""
            task_row_value = self.conn.execute(
                self._format_query("SELECT * FROM site_asr_tasks WHERE id = {}" + lock_clause),
                (task_id,),
            ).fetchone()
            if task_row_value is None:
                raise KeyError(task_id)
            task = task_row(self._row_dict(task_row_value))

            self.conn.execute(
                self._format_query(
                    """
                    UPDATE site_asr_tasks
                    SET status = {}, error = {}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = {}
                    """
                ),
                (status, error, task_id),
            )

            consume_entry = self.conn.execute(
                self._format_query(
                    """
                    SELECT 1 FROM site_point_ledger
                    WHERE task_id = {} AND kind = 'consume'
                    LIMIT 1
                    """
                ),
                (task_id,),
            ).fetchone()
            refund_entry = self.conn.execute(
                self._format_query(
                    """
                    SELECT 1 FROM site_point_ledger
                    WHERE task_id = {} AND kind = 'transcription_refund'
                    LIMIT 1
                    """
                ),
                (task_id,),
            ).fetchone()
            if consume_entry is not None and refund_entry is None:
                self._apply_points_without_commit(
                    user_id=task["user_id"],
                    delta=int(task["points_cost"]),
                    kind="transcription_refund",
                    note="transcription failed",
                    task_id=task_id,
                )
            return self.get_task(task_id)

        return self._run_atomic(fail_and_refund)

    def fail_task_by_media_id_with_points_refund(
        self,
        media_id: str,
        error: str,
    ) -> dict[str, Any] | None:
        task = self.get_task_by_media_id(media_id)
        if task is None:
            return None
        return self.fail_task_with_points_refund(task["id"], error)

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

    def mark_task_starting_with_points(
        self,
        task_id: str,
        user_id: str,
        *,
        notify_on_complete: bool = False,
        notification_template_id: str = "",
    ) -> dict[str, Any]:
        """Atomically charge the task owner and move an uploaded task to starting."""

        notification_template_id = notification_template_id.strip()
        notification_enabled = bool(notify_on_complete and notification_template_id)

        def charge_and_start() -> dict[str, Any]:
            lock_clause = " FOR UPDATE" if self.backend == "postgres" else ""
            task_row_value = self.conn.execute(
                self._format_query("SELECT * FROM site_asr_tasks WHERE id = {}" + lock_clause),
                (task_id,),
            ).fetchone()
            if task_row_value is None:
                raise KeyError(task_id)
            task = task_row(self._row_dict(task_row_value))
            if task["user_id"] != user_id:
                raise KeyError(task_id)
            if task["status"] != "uploaded":
                raise ValueError(f"Task status {task['status']} cannot be started.")

            user_row = self.conn.execute(
                self._format_query("SELECT * FROM site_users WHERE id = {}" + lock_clause),
                (user_id,),
            ).fetchone()
            if user_row is None:
                raise KeyError(user_id)
            user = self._row_dict(user_row)
            points_cost = int(task["points_cost"])
            points_balance = int(user["points_balance"])
            if points_balance < points_cost:
                raise ValueError(
                    f"点数不足：本次需要 {points_cost} 点，当前余额 {points_balance} 点。"
                )

            self._apply_points_without_commit(
                user_id=user_id,
                delta=-points_cost,
                kind="consume",
                note="confirmed asr task",
                task_id=task_id,
            )
            updated = self.conn.execute(
                self._format_query(
                    """
                    UPDATE site_asr_tasks
                    SET status = 'starting',
                        notify_on_complete = {},
                        notification_template_id = {},
                        notification_job_id = NULL,
                        notification_status = {},
                        notification_attempts = 0,
                        notification_last_error = NULL,
                        notification_sent_at = NULL,
                        confirmed_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = {} AND status = 'uploaded'
                    RETURNING *
                    """
                ),
                (
                    notification_enabled,
                    notification_template_id if notification_enabled else "",
                    "pending" if notification_enabled else "disabled",
                    task_id,
                ),
            ).fetchone()
            if updated is None:
                raise ValueError("Task status changed while starting.")
            return task_row(self._row_dict(updated))

        return self._run_atomic(charge_and_start)

    def enqueue_task_notification(self, task_id: str) -> str | None:
        """Atomically add one notification job for a completed pending task."""

        def enqueue() -> str | None:
            lock_clause = " FOR UPDATE" if self.backend == "postgres" else ""
            row = self.conn.execute(
                self._format_query("SELECT * FROM site_asr_tasks WHERE id = {}" + lock_clause),
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = task_row(self._row_dict(row))
            if (
                task["status"] != "completed"
                or task["notification_status"] != "pending"
                or task["notification_job_id"]
            ):
                return None

            notification_job_id = self.next_id("job")
            self.conn.execute(
                self._format_query(
                    """
                    INSERT INTO jobs(id, type, status, payload, record_id, error)
                    VALUES ({}, 'send_site_notification', 'pending', {}, NULL, NULL)
                    """
                ),
                (notification_job_id, self._json_param({"task_id": task_id})),
            )
            self.conn.execute(
                self._format_query(
                    """
                    UPDATE site_asr_tasks
                    SET notification_job_id = {}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = {}
                    """
                ),
                (notification_job_id, task_id),
            )
            return notification_job_id

        return self._run_atomic(enqueue)

    def enqueue_pending_task_notifications(self, limit: int = 100) -> list[str]:
        rows = self._fetchall(
            """
            SELECT id
            FROM site_asr_tasks
            WHERE status = 'completed'
              AND notification_status = 'pending'
              AND notification_job_id IS NULL
            ORDER BY updated_at, id
            LIMIT {}
            """,
            (max(1, limit),),
        )
        job_ids = []
        for row in rows:
            job_id = self.enqueue_task_notification(self._row_dict(row)["id"])
            if job_id:
                job_ids.append(job_id)
        return job_ids

    def begin_task_notification(self, task_id: str) -> dict[str, Any] | None:
        """Record a delivery attempt unless this notification was already finalized."""

        def begin() -> dict[str, Any] | None:
            lock_clause = " FOR UPDATE" if self.backend == "postgres" else ""
            row = self.conn.execute(
                self._format_query("SELECT * FROM site_asr_tasks WHERE id = {}" + lock_clause),
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            task = task_row(self._row_dict(row))
            if task["status"] != "completed" or task["notification_status"] != "pending":
                return None
            updated = self.conn.execute(
                self._format_query(
                    """
                    UPDATE site_asr_tasks
                    SET notification_attempts = notification_attempts + 1,
                        notification_last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = {} AND notification_status = 'pending'
                    RETURNING *
                    """
                ),
                (task_id,),
            ).fetchone()
            return task_row(self._row_dict(updated)) if updated is not None else None

        return self._run_atomic(begin)

    def mark_task_notification_sent(self, task_id: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET notification_status = 'sent',
                notification_last_error = NULL,
                notification_sent_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {} AND notification_status = 'pending'
            """,
            (task_id,),
        )
        return self.get_task(task_id)

    def mark_task_notification_failed(self, task_id: str, error: str) -> dict[str, Any]:
        self._execute(
            """
            UPDATE site_asr_tasks
            SET notification_status = 'failed',
                notification_last_error = {},
                updated_at = CURRENT_TIMESTAMP
            WHERE id = {} AND notification_status = 'pending'
            """,
            (error[:1000], task_id),
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
        task_columns = ", ".join(f"t.{column} AS {column}" for column in TASK_SUMMARY_COLUMNS)

        def fetch_metadata_and_delete() -> dict[str, Any]:
            row = self.conn.execute(
                self._format_query(
                    f"""
                    SELECT {task_columns}, m.object_name AS object_name
                    FROM site_asr_tasks AS t
                    LEFT JOIN media_records AS m ON m.id = t.media_id
                    WHERE t.id = {{}}
                    """
                ),
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            deleted = self.conn.execute(
                self._format_query("DELETE FROM site_asr_tasks WHERE id = {} RETURNING id"),
                (task_id,),
            ).fetchone()
            if deleted is None:
                raise KeyError(task_id)
            row_dict = self._row_dict(row)
            return {
                **task_summary_row(row_dict),
                "object_name": row_dict.get("object_name"),
            }

        return self._run_atomic(fetch_metadata_and_delete)

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
                CREATE INDEX IF NOT EXISTS idx_site_point_ledger_user_created
                ON site_point_ledger(user_id, created_at DESC, id DESC)
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
                CREATE TABLE IF NOT EXISTS site_user_agreements(
                    user_id TEXT NOT NULL REFERENCES site_users(id) ON DELETE CASCADE,
                    agreement_version TEXT NOT NULL,
                    accepted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    client TEXT NOT NULL DEFAULT 'unknown',
                    PRIMARY KEY(user_id, agreement_version)
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
                    notify_on_complete BOOLEAN NOT NULL DEFAULT FALSE,
                    notification_template_id TEXT NOT NULL DEFAULT '',
                    notification_job_id TEXT,
                    notification_status TEXT NOT NULL DEFAULT 'disabled',
                    notification_attempts INTEGER NOT NULL DEFAULT 0,
                    notification_last_error TEXT,
                    notification_sent_at TIMESTAMPTZ,
                    editable_utterances JSONB NOT NULL DEFAULT '[]'::jsonb,
                    error TEXT,
                    confirmed_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
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
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notify_on_complete BOOLEAN NOT NULL DEFAULT FALSE")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notification_template_id TEXT NOT NULL DEFAULT ''")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notification_job_id TEXT")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notification_status TEXT NOT NULL DEFAULT 'disabled'")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notification_attempts INTEGER NOT NULL DEFAULT 0")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notification_last_error TEXT")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMPTZ")
            self.conn.execute("ALTER TABLE site_asr_tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
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
                CREATE INDEX IF NOT EXISTS idx_site_point_ledger_user_created
                ON site_point_ledger(user_id, created_at DESC, id DESC);
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
                CREATE TABLE IF NOT EXISTS site_user_agreements(
                    user_id TEXT NOT NULL REFERENCES site_users(id) ON DELETE CASCADE,
                    agreement_version TEXT NOT NULL,
                    accepted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    client TEXT NOT NULL DEFAULT 'unknown',
                    PRIMARY KEY(user_id, agreement_version)
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
                    notify_on_complete INTEGER NOT NULL DEFAULT 0,
                    notification_template_id TEXT NOT NULL DEFAULT '',
                    notification_job_id TEXT,
                    notification_status TEXT NOT NULL DEFAULT 'disabled',
                    notification_attempts INTEGER NOT NULL DEFAULT 0,
                    notification_last_error TEXT,
                    notification_sent_at TEXT,
                    editable_utterances TEXT NOT NULL DEFAULT '[]',
                    error TEXT,
                    confirmed_at TEXT,
                    completed_at TEXT,
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
            self._ensure_sqlite_column("site_asr_tasks", "notify_on_complete", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_sqlite_column("site_asr_tasks", "notification_template_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_sqlite_column("site_asr_tasks", "notification_job_id", "TEXT")
            self._ensure_sqlite_column("site_asr_tasks", "notification_status", "TEXT NOT NULL DEFAULT 'disabled'")
            self._ensure_sqlite_column("site_asr_tasks", "notification_attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_sqlite_column("site_asr_tasks", "notification_last_error", "TEXT")
            self._ensure_sqlite_column("site_asr_tasks", "notification_sent_at", "TEXT")
            self._ensure_sqlite_column("site_asr_tasks", "completed_at", "TEXT")
            self._ensure_sqlite_column("site_asr_tasks", "editable_utterances", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_sqlite_column("site_asr_tasks", "raw_result", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_task_indexes()
        self._ensure_agreement_indexes()
        if self.backend == "sqlite":
            self.conn.commit()

    def _ensure_task_indexes(self) -> None:
        statements = (
            """
            CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_user_created
            ON site_asr_tasks(user_id, created_at DESC, id DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_media_id
            ON site_asr_tasks(media_id)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_status_updated
            ON site_asr_tasks(status, updated_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_expires_at
            ON site_asr_tasks(expires_at)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_site_asr_tasks_local_expires_at
            ON site_asr_tasks(local_expires_at)
            """,
        )
        for statement in statements:
            self.conn.execute(statement)

    def _ensure_agreement_indexes(self) -> None:
        self.conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_site_user_agreements_user_accepted
            ON site_user_agreements(user_id, accepted_at DESC)
            """
        )

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
    pending_dir = pending_upload_root()
    pending_dir.mkdir(parents=True, exist_ok=True)
    return pending_dir / f"{task_id}-{safe_name}"


def pending_upload_root() -> Path:
    configured = os.getenv("RECORDFLOW_PENDING_UPLOAD_ROOT", "").strip()
    if configured:
        return Path(configured)
    return PENDING_UPLOAD_DIR


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


def user_agreement_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "agreement_version": row["agreement_version"],
        "accepted_at": stringify_time(row["accepted_at"]),
        "client": row["client"],
    }


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
        "notify_on_complete": bool(row["notify_on_complete"]),
        "notification_template_id": row["notification_template_id"],
        "notification_job_id": row["notification_job_id"],
        "notification_status": row["notification_status"],
        "notification_attempts": int(row["notification_attempts"] or 0),
        "notification_last_error": row["notification_last_error"],
        "notification_sent_at": stringify_time(row["notification_sent_at"]),
        "utterances": utterances,
        "error": row["error"],
        "confirmed_at": stringify_time(row["confirmed_at"]),
        "completed_at": stringify_time(row["completed_at"]),
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
        "notify_on_complete": bool(row["notify_on_complete"]),
        "notification_template_id": row["notification_template_id"],
        "notification_job_id": row["notification_job_id"],
        "notification_status": row["notification_status"],
        "notification_attempts": int(row["notification_attempts"] or 0),
        "notification_last_error": row["notification_last_error"],
        "notification_sent_at": stringify_time(row["notification_sent_at"]),
        "error": row["error"],
        "confirmed_at": stringify_time(row["confirmed_at"]),
        "completed_at": stringify_time(row["completed_at"]),
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


def task_summary_with_media_row(row: dict[str, Any]) -> dict[str, Any]:
    task = task_summary_row(row)
    media_id = row.get("media_summary_id")
    if not media_id:
        return {**task, "media": None}
    return {
        **task,
        "media": {
            "id": media_id,
            "source_name": row.get("media_summary_source_name"),
            "stored_name": row.get("media_summary_stored_name"),
            "url": row.get("media_summary_url"),
            "public_url": row.get("media_summary_public_url"),
            "content_type": row.get("media_summary_content_type"),
            "status": row.get("media_summary_status"),
            "created_at": stringify_time(row.get("media_summary_created_at")),
            "updated_at": stringify_time(row.get("media_summary_updated_at")),
        },
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
    utterances: list[dict[str, Any]] = []

    def append_raw_utterances(raw_utterances: Any) -> None:
        if not isinstance(raw_utterances, list):
            return
        for utterance in raw_utterances:
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

    append_raw_utterances(raw_result.get("utterances"))
    result_items = raw_result.get("result")
    if not utterances and isinstance(result_items, list):
        for item in result_items:
            if not isinstance(item, dict):
                continue
            append_raw_utterances(item.get("utterances"))
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
