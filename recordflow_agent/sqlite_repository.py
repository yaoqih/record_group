from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from recordflow_agent.schemas import (
    ChangeEvent,
    ChangeType,
    EvidenceAnchor,
    ObjectType,
    Record,
    RecordDigest,
    StateObject,
    TopicBlock,
    TranscriptSegment,
    Workspace,
)


class SQLiteRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self._init_schema()
        self.workspaces = WorkspaceMapping(self)
        self.records = RecordMapping(self)
        self.segments = SegmentMapping(self)
        self.evidence = EvidenceMapping(self)
        self.topic_blocks = TopicBlockMapping(self)
        self.state_objects = StateObjectMapping(self)
        self.change_events = ChangeEventMapping(self)

    def close(self) -> None:
        self.conn.close()

    def next_id(self, prefix: str) -> str:
        with self.lock:
            now = int(time.time() * 1000)
            row = self.conn.execute("SELECT next_value FROM id_counters WHERE prefix = ?", (prefix,)).fetchone()
            if row is None:
                next_value = 1
                self.conn.execute(
                    "INSERT INTO id_counters(prefix, next_value) VALUES (?, ?)",
                    (prefix, 2),
                )
            else:
                next_value = int(row["next_value"])
                self.conn.execute(
                    "UPDATE id_counters SET next_value = ? WHERE prefix = ?",
                    (next_value + 1, prefix),
                )
            self.conn.commit()
            return f"{prefix}_{now}_{next_value:06d}"

    def create_workspace(self, name: str, profile: str) -> str:
        workspace_id = self.next_id("ws")
        self.conn.execute(
            "INSERT INTO workspaces(id, name, profile) VALUES (?, ?, ?)",
            (workspace_id, name, profile),
        )
        self.conn.commit()
        return workspace_id

    def list_workspaces(self) -> list[Workspace]:
        rows = self.conn.execute("SELECT * FROM workspaces ORDER BY rowid").fetchall()
        return [Workspace(id=row["id"], name=row["name"], profile=row["profile"]) for row in rows]

    def add_record(self, workspace_id: str, title: str, text: str) -> Record:
        record = Record(
            id=self.next_id("rec"),
            workspace_id=workspace_id,
            title=title,
            text=text,
        )
        self.conn.execute(
            "INSERT INTO records(id, workspace_id, title, text) VALUES (?, ?, ?, ?)",
            (record.id, record.workspace_id, record.title, record.text),
        )
        self.conn.commit()
        return record

    def list_records(self, workspace_id: str | None = None) -> list[Record]:
        if workspace_id is None:
            rows = self.conn.execute("SELECT * FROM records ORDER BY rowid").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM records WHERE workspace_id = ? ORDER BY rowid",
                (workspace_id,),
            ).fetchall()
        return [
            Record(
                id=row["id"],
                workspace_id=row["workspace_id"],
                title=row["title"],
                text=row["text"],
            )
            for row in rows
        ]

    def add_segment(self, record_id: str, text: str) -> TranscriptSegment:
        segment = TranscriptSegment(
            id=self.next_id("seg"),
            record_id=record_id,
            text=text,
        )
        self.conn.execute(
            "INSERT INTO transcript_segments(id, record_id, text, confidence) VALUES (?, ?, ?, ?)",
            (segment.id, segment.record_id, segment.text, segment.confidence),
        )
        self.conn.commit()
        return segment

    def add_evidence(self, record_id: str, segment_id: str, quote: str) -> EvidenceAnchor:
        evidence = EvidenceAnchor(
            id=self.next_id("ev"),
            record_id=record_id,
            segment_id=segment_id,
            quote=quote,
        )
        self.conn.execute(
            "INSERT INTO evidence_anchors(id, record_id, segment_id, quote) VALUES (?, ?, ?, ?)",
            (evidence.id, evidence.record_id, evidence.segment_id, evidence.quote),
        )
        self.conn.commit()
        return evidence

    def add_topic_block(self, topic_block: TopicBlock) -> TopicBlock:
        self.conn.execute(
            """
            INSERT INTO topic_blocks(id, record_id, topic, summary, segment_ids, importance)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                topic_block.id,
                topic_block.record_id,
                topic_block.topic,
                topic_block.summary,
                json.dumps(topic_block.segment_ids, ensure_ascii=False),
                topic_block.importance,
            ),
        )
        self.conn.commit()
        return topic_block

    def add_state_object(self, state_object: StateObject) -> StateObject:
        self.conn.execute(
            """
            INSERT INTO state_objects(
                id, workspace_id, type, title, summary, status, payload,
                evidence_ids, version, confidence
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state_object.id,
                state_object.workspace_id,
                state_object.type.value,
                state_object.title,
                state_object.summary,
                state_object.status,
                dump_json(state_object.payload),
                dump_json(state_object.evidence_ids),
                state_object.version,
                state_object.confidence,
            ),
        )
        self.conn.commit()
        return state_object

    def update_state_object(self, state_object: StateObject) -> StateObject:
        state_object.version += 1
        self.conn.execute(
            """
            UPDATE state_objects
            SET title = ?, summary = ?, status = ?, payload = ?, evidence_ids = ?,
                version = ?, confidence = ?
            WHERE id = ?
            """,
            (
                state_object.title,
                state_object.summary,
                state_object.status,
                dump_json(state_object.payload),
                dump_json(state_object.evidence_ids),
                state_object.version,
                state_object.confidence,
                state_object.id,
            ),
        )
        self.conn.commit()
        return state_object

    def add_change_event(self, change_event: ChangeEvent) -> ChangeEvent:
        self.conn.execute(
            """
            INSERT INTO change_events(
                id, workspace_id, record_id, change_type, summary, target_object_id,
                candidate_object_id, requires_review, evidence_ids, field_changes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                change_event.id,
                change_event.workspace_id,
                change_event.record_id,
                change_event.change_type.value,
                change_event.summary,
                change_event.target_object_id,
                change_event.candidate_object_id,
                int(change_event.requires_review),
                dump_json(change_event.evidence_ids),
                dump_json(change_event.field_changes),
            ),
        )
        self.conn.commit()
        return change_event

    def list_state_objects(self, workspace_id: str) -> list[StateObject]:
        rows = self.conn.execute(
            "SELECT * FROM state_objects WHERE workspace_id = ? ORDER BY rowid",
            (workspace_id,),
        ).fetchall()
        return [state_object_from_row(row) for row in rows]

    def get_state_object(self, state_object_id: str) -> StateObject:
        row = self.conn.execute(
            "SELECT * FROM state_objects WHERE id = ?",
            (state_object_id,),
        ).fetchone()
        if row is None:
            raise KeyError(state_object_id)
        return state_object_from_row(row)

    def patch_state_object(
        self,
        state_object_id: str,
        *,
        record_id: str,
        summary: str | None = None,
        status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[StateObject, ChangeEvent]:
        state_object = self.get_state_object(state_object_id)
        field_changes: dict[str, dict[str, Any]] = {}
        if summary is not None and summary != state_object.summary:
            field_changes["summary"] = {"from": state_object.summary, "to": summary}
            state_object.summary = summary
        if status is not None and status != state_object.status:
            field_changes["status"] = {"from": state_object.status, "to": status}
            state_object.status = status
        if payload:
            for key, new_value in payload.items():
                old_value = state_object.payload.get(key)
                if old_value != new_value:
                    state_object.payload[key] = new_value
                    field_changes[f"payload.{key}"] = {"from": old_value, "to": new_value}
        self.update_state_object(state_object)
        change = ChangeEvent(
            id=self.next_id("chg"),
            workspace_id=state_object.workspace_id,
            record_id=record_id,
            change_type=ChangeType.UPDATE,
            target_object_id=state_object.id,
            candidate_object_id=state_object.id,
            summary=f"用户更新 {state_object.type.value}: {state_object.title}",
            requires_review=False,
            evidence_ids=list(state_object.evidence_ids),
            field_changes=field_changes,
        )
        return self.get_state_object(state_object.id), self.add_change_event(change)

    def list_change_events(self, workspace_id: str) -> list[ChangeEvent]:
        rows = self.conn.execute(
            "SELECT * FROM change_events WHERE workspace_id = ? ORDER BY rowid",
            (workspace_id,),
        ).fetchall()
        return [change_event_from_row(row) for row in rows]

    def save_record_digest(self, digest: RecordDigest | dict[str, Any]) -> dict[str, Any]:
        from recordflow_agent.serialization import to_jsonable

        digest_json = to_jsonable(digest)
        self.conn.execute(
            """
            INSERT INTO record_digests(record_id, workspace_id, digest_json, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(record_id)
            DO UPDATE SET workspace_id = excluded.workspace_id,
                          digest_json = excluded.digest_json,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (
                digest_json["record_id"],
                digest_json["workspace_id"],
                dump_json(digest_json),
            ),
        )
        self.conn.commit()
        return digest_json

    def get_record_digest(self, record_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT digest_json FROM record_digests WHERE record_id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return load_json(row["digest_json"])

    def clear_all(self) -> None:
        with self.lock:
            for table in [
                "id_counters",
                "workspaces",
                "records",
                "transcript_segments",
                "evidence_anchors",
                "topic_blocks",
                "state_objects",
                "change_events",
                "jobs",
                "record_digests",
                "media_records",
            ]:
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.commit()

    def list_review_items(self, workspace_id: str) -> list[ChangeEvent]:
        rows = self.conn.execute(
            """
            SELECT * FROM change_events
            WHERE workspace_id = ? AND requires_review = 1 AND review_status = 'pending'
            ORDER BY rowid
            """,
            (workspace_id,),
        ).fetchall()
        return [change_event_from_row(row) for row in rows]

    def set_review_status(self, change_event_id: str, status: str) -> None:
        if status not in {"accepted", "ignored"}:
            raise ValueError("Review status must be accepted or ignored.")
        self.conn.execute(
            "UPDATE change_events SET review_status = ? WHERE id = ?",
            (status, change_event_id),
        )
        self.conn.commit()

    def enqueue_record_job(
        self,
        workspace_id: str,
        title: str,
        text: str,
        use_llm: bool,
    ) -> str:
        job_id = self.next_id("job")
        self.conn.execute(
            """
            INSERT INTO jobs(id, type, status, payload, record_id, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "process_record",
                "pending",
                dump_json(
                    {
                        "workspace_id": workspace_id,
                        "title": title,
                        "text": text,
                        "use_llm": use_llm,
                    }
                ),
                None,
                None,
            ),
        )
        self.conn.commit()
        return job_id

    def add_media_record(
        self,
        workspace_id: str,
        source_name: str,
        stored_name: str,
        url: str,
        public_url: str,
        object_name: str,
        content_type: str,
        original_size_bytes: int | None,
        compressed_size_bytes: int,
        compression_codec: str | None,
    ) -> str:
        media_id = self.next_id("med")
        self.conn.execute(
            """
            INSERT INTO media_records(
                id, workspace_id, source_name, stored_name, url, public_url,
                object_name, content_type, original_size_bytes, compressed_size_bytes,
                compression_codec, status, asr_task_id, transcript_text, utterances,
                raw_asr_result, record_id, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                media_id,
                workspace_id,
                source_name,
                stored_name,
                url,
                public_url,
                object_name,
                content_type,
                original_size_bytes,
                compressed_size_bytes,
                compression_codec,
                "uploaded",
                None,
                None,
                dump_json([]),
                dump_json({}),
                None,
                None,
            ),
        )
        self.conn.commit()
        return media_id

    def enqueue_media_transcription_job(
        self,
        workspace_id: str,
        media_id: str,
        title: str,
        use_llm: bool,
    ) -> str:
        job_id = self.next_id("job")
        self.conn.execute(
            """
            INSERT INTO jobs(id, type, status, payload, record_id, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "transcribe_media",
                "pending",
                dump_json(
                    {
                        "workspace_id": workspace_id,
                        "media_id": media_id,
                        "title": title,
                        "use_llm": use_llm,
                    }
                ),
                None,
                None,
            ),
        )
        self.conn.commit()
        return job_id

    def enqueue_site_task_prepare_job(self, task_id: str) -> str:
        job_id = self.next_id("job")
        self.conn.execute(
            """
            INSERT INTO jobs(id, type, status, payload, record_id, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "prepare_site_task",
                "pending",
                dump_json({"task_id": task_id}),
                None,
                None,
            ),
        )
        self.conn.commit()
        return job_id

    def enqueue_media_compression_job(
        self,
        workspace_id: str,
        media_id: str,
        title: str,
        use_llm: bool,
    ) -> str:
        job_id = self.next_id("job")
        self.conn.execute(
            """
            INSERT INTO jobs(id, type, status, payload, record_id, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "compress_media",
                "pending",
                dump_json(
                    {
                        "workspace_id": workspace_id,
                        "media_id": media_id,
                        "title": title,
                        "use_llm": use_llm,
                    }
                ),
                None,
                None,
            ),
        )
        self.conn.commit()
        return job_id

    def enqueue_cleanup_job(self) -> str:
        job_id = self.next_id("job")
        self.conn.execute(
            """
            INSERT INTO jobs(id, type, status, payload, record_id, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                "cleanup_expired_media",
                "pending",
                dump_json({}),
                None,
                None,
            ),
        )
        self.conn.commit()
        return job_id

    def replace_media_object(
        self,
        media_id: str,
        *,
        stored_name: str,
        url: str,
        public_url: str,
        object_name: str,
        content_type: str,
        compressed_size_bytes: int,
        compression_codec: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE media_records
            SET stored_name = ?,
                url = ?,
                public_url = ?,
                object_name = ?,
                content_type = ?,
                compressed_size_bytes = ?,
                compression_codec = ?,
                status = 'compressed',
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                stored_name,
                url,
                public_url,
                object_name,
                content_type,
                compressed_size_bytes,
                compression_codec,
                media_id,
            ),
        )
        self.conn.commit()

    def update_media_status(
        self,
        media_id: str,
        status: str,
        *,
        asr_task_id: str | None = None,
        transcript_text: str | None = None,
        utterances: list[dict[str, Any]] | None = None,
        raw_asr_result: dict[str, Any] | None = None,
        record_id: str | None = None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE media_records
            SET status = ?,
                asr_task_id = COALESCE(?, asr_task_id),
                transcript_text = COALESCE(?, transcript_text),
                utterances = COALESCE(?, utterances),
                raw_asr_result = COALESCE(?, raw_asr_result),
                record_id = COALESCE(?, record_id),
                error = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                asr_task_id,
                transcript_text,
                dump_json(utterances) if utterances is not None else None,
                dump_json(raw_asr_result) if raw_asr_result is not None else None,
                record_id,
                error,
                media_id,
            ),
        )
        self.conn.commit()

    def get_media_record(self, media_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM media_records WHERE id = ?", (media_id,)).fetchone()
        if row is None:
            raise KeyError(media_id)
        return media_record_from_row(row)

    def delete_media_record(self, media_id: str) -> None:
        with self.lock:
            cursor = self.conn.execute("DELETE FROM media_records WHERE id = ?", (media_id,))
            if cursor.rowcount == 0:
                raise KeyError(media_id)
            self.conn.commit()

    def list_media_records(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM media_records WHERE workspace_id = ? ORDER BY rowid",
            (workspace_id,),
        ).fetchall()
        return [media_record_from_row(row) for row in rows]

    def claim_next_job(self, job_types: set[str] | None = None) -> dict[str, Any] | None:
        with self.lock:
            if job_types:
                placeholders = ",".join("?" for _ in job_types)
                row = self.conn.execute(
                    f"""
                    SELECT * FROM jobs
                    WHERE status = 'pending' AND type IN ({placeholders})
                    ORDER BY rowid
                    LIMIT 1
                    """,
                    tuple(sorted(job_types)),
                ).fetchone()
            else:
                row = self.conn.execute(
                    "SELECT * FROM jobs WHERE status = 'pending' ORDER BY rowid LIMIT 1"
                ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (row["id"],),
            )
            self.conn.commit()
            return job_from_row(row) | {"status": "running"}

    def requeue_stale_running_jobs(self, max_age_seconds: int = 900) -> int:
        with self.lock:
            cursor = self.conn.execute(
                """
                UPDATE jobs
                SET status = 'pending',
                    error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                  AND updated_at < datetime('now', ?)
                """,
                (
                    f"Requeued stale running job after {max_age_seconds} seconds.",
                    f"-{max_age_seconds} seconds",
                ),
            )
            self.conn.commit()
            return cursor.rowcount

    def complete_job(self, job_id: str, record_id: str) -> None:
        self.conn.execute(
            """
            UPDATE jobs
            SET status = 'completed', record_id = ?, error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (record_id, job_id),
        )
        self.conn.commit()

    def fail_job(self, job_id: str, error: str) -> None:
        self.conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (error, job_id),
        )
        self.conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return job_from_row(row)

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS id_counters(
                prefix TEXT PRIMARY KEY,
                next_value INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspaces(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                profile TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS records(
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                title TEXT NOT NULL,
                text TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transcript_segments(
                id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL,
                text TEXT NOT NULL,
                speaker TEXT,
                start_time TEXT,
                end_time TEXT,
                confidence REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evidence_anchors(
                id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                quote TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT
            );
            CREATE TABLE IF NOT EXISTS topic_blocks(
                id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                segment_ids TEXT NOT NULL,
                importance TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state_objects(
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                evidence_ids TEXT NOT NULL,
                version INTEGER NOT NULL,
                confidence REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS change_events(
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                target_object_id TEXT,
                candidate_object_id TEXT NOT NULL,
                requires_review INTEGER NOT NULL,
                evidence_ids TEXT NOT NULL,
                field_changes TEXT NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS jobs(
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                record_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS record_digests(
                record_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                digest_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS media_records(
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                url TEXT NOT NULL,
                public_url TEXT NOT NULL,
                object_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                original_size_bytes INTEGER,
                compressed_size_bytes INTEGER NOT NULL,
                compression_codec TEXT,
                status TEXT NOT NULL,
                asr_task_id TEXT,
                transcript_text TEXT,
                utterances TEXT NOT NULL,
                raw_asr_result TEXT NOT NULL,
                record_id TEXT,
                error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.conn.commit()


class WorkspaceMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo

    def __getitem__(self, workspace_id: str) -> Workspace:
        row = self.repo.conn.execute(
            "SELECT * FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise KeyError(workspace_id)
        return Workspace(id=row["id"], name=row["name"], profile=row["profile"])


class RecordMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo


class SegmentMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo

    def __getitem__(self, segment_id: str) -> TranscriptSegment:
        row = self.repo.conn.execute(
            "SELECT * FROM transcript_segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        if row is None:
            raise KeyError(segment_id)
        return TranscriptSegment(
            id=row["id"],
            record_id=row["record_id"],
            text=row["text"],
            speaker=row["speaker"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            confidence=row["confidence"],
        )

    def __contains__(self, segment_id: str) -> bool:
        row = self.repo.conn.execute(
            "SELECT 1 FROM transcript_segments WHERE id = ?",
            (segment_id,),
        ).fetchone()
        return row is not None


class EvidenceMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo


class TopicBlockMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo


class StateObjectMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo


class ChangeEventMapping:
    def __init__(self, repo: SQLiteRepository) -> None:
        self.repo = repo


def state_object_from_row(row: sqlite3.Row) -> StateObject:
    return StateObject(
        id=row["id"],
        workspace_id=row["workspace_id"],
        type=ObjectType(row["type"]),
        title=row["title"],
        summary=row["summary"],
        status=row["status"],
        payload=load_json(row["payload"]),
        evidence_ids=load_json(row["evidence_ids"]),
        version=row["version"],
        confidence=row["confidence"],
    )


def change_event_from_row(row: sqlite3.Row) -> ChangeEvent:
    return ChangeEvent(
        id=row["id"],
        workspace_id=row["workspace_id"],
        record_id=row["record_id"],
        change_type=ChangeType(row["change_type"]),
        summary=row["summary"],
        target_object_id=row["target_object_id"],
        candidate_object_id=row["candidate_object_id"],
        requires_review=bool(row["requires_review"]),
        evidence_ids=load_json(row["evidence_ids"]),
        field_changes=load_json(row["field_changes"]),
    )


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_json(value: str) -> Any:
    return json.loads(value)


def job_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "status": row["status"],
        "payload": load_json(row["payload"]),
        "record_id": row["record_id"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def media_record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "workspace_id": row["workspace_id"],
        "source_name": row["source_name"],
        "stored_name": row["stored_name"],
        "url": row["url"],
        "public_url": row["public_url"],
        "object_name": row["object_name"],
        "content_type": row["content_type"],
        "original_size_bytes": row["original_size_bytes"],
        "compressed_size_bytes": row["compressed_size_bytes"],
        "compression_codec": row["compression_codec"],
        "status": row["status"],
        "asr_task_id": row["asr_task_id"],
        "transcript_text": row["transcript_text"],
        "utterances": load_json(row["utterances"]),
        "raw_asr_result": load_json(row["raw_asr_result"]),
        "record_id": row["record_id"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
