from __future__ import annotations

import time
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from psycopg.rows import dict_row

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


CONNECTION_CHECK_INTERVAL_SECONDS = 30.0


class PostgresRepository:
    def __init__(self, database_url: str, initialize: bool = True) -> None:
        self.database_url = database_url
        self._conn: Any | None = None
        self._last_connection_check_at = 0.0
        self._conn = self._connect()
        if initialize:
            self._init_schema()
        self.workspaces = WorkspaceMapping(self)
        self.records = RecordMapping(self)
        self.segments = SegmentMapping(self)
        self.evidence = EvidenceMapping(self)
        self.topic_blocks = TopicBlockMapping(self)
        self.state_objects = StateObjectMapping(self)
        self.change_events = ChangeEventMapping(self)

    @property
    def conn(self):
        self._ensure_connection()
        return self._conn

    def close(self) -> None:
        self._close_current_connection()

    def _connect(self):
        conn = psycopg.connect(self.database_url, row_factory=dict_row)
        conn.autocommit = True
        self._last_connection_check_at = time.monotonic()
        return conn

    def _ensure_connection(self) -> None:
        if self._conn is None:
            self._conn = self._connect()
            return
        if bool(getattr(self._conn, "closed", False)):
            self._conn = self._connect()
            return
        now = time.monotonic()
        if now - self._last_connection_check_at < CONNECTION_CHECK_INTERVAL_SECONDS:
            return
        try:
            self._conn.execute("SELECT 1").fetchone()
        except psycopg.Error:
            self._close_current_connection()
            self._conn = self._connect()
            return
        self._last_connection_check_at = now

    def _close_current_connection(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.close()
        except Exception:
            pass

    def next_id(self, prefix: str) -> str:
        now = int(time.time() * 1000)
        with self.conn.transaction():
            row = self.conn.execute(
                """
                INSERT INTO id_counters(prefix, next_value)
                VALUES (%s, %s)
                ON CONFLICT (prefix)
                DO UPDATE SET next_value = id_counters.next_value + 1
                RETURNING next_value
                """,
                (prefix, 2),
            ).fetchone()
        next_value = int(row["next_value"]) - 1
        return f"{prefix}_{now}_{next_value:06d}"

    def create_workspace(self, name: str, profile: str) -> str:
        workspace_id = self.next_id("ws")
        self.conn.execute(
            "INSERT INTO workspaces(id, name, profile) VALUES (%s, %s, %s)",
            (workspace_id, name, profile),
        )
        self.conn.commit()
        return workspace_id

    def list_workspaces(self) -> list[Workspace]:
        rows = self.conn.execute("SELECT * FROM workspaces ORDER BY id").fetchall()
        return [Workspace(id=row["id"], name=row["name"], profile=row["profile"]) for row in rows]

    def add_record(self, workspace_id: str, title: str, text: str) -> Record:
        record = Record(
            id=self.next_id("rec"),
            workspace_id=workspace_id,
            title=title,
            text=text,
        )
        self.conn.execute(
            "INSERT INTO records(id, workspace_id, title, text) VALUES (%s, %s, %s, %s)",
            (record.id, record.workspace_id, record.title, record.text),
        )
        self.conn.commit()
        return record

    def list_records(self, workspace_id: str | None = None) -> list[Record]:
        if workspace_id is None:
            rows = self.conn.execute("SELECT * FROM records ORDER BY id").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM records WHERE workspace_id = %s ORDER BY id",
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
            """
            INSERT INTO transcript_segments(id, record_id, text, confidence)
            VALUES (%s, %s, %s, %s)
            """,
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
            """
            INSERT INTO evidence_anchors(id, record_id, segment_id, quote)
            VALUES (%s, %s, %s, %s)
            """,
            (evidence.id, evidence.record_id, evidence.segment_id, evidence.quote),
        )
        self.conn.commit()
        return evidence

    def add_topic_block(self, topic_block: TopicBlock) -> TopicBlock:
        self.conn.execute(
            """
            INSERT INTO topic_blocks(id, record_id, topic, summary, segment_ids, importance)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                topic_block.id,
                topic_block.record_id,
                topic_block.topic,
                topic_block.summary,
                Jsonb(topic_block.segment_ids),
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                state_object.id,
                state_object.workspace_id,
                state_object.type.value,
                state_object.title,
                state_object.summary,
                state_object.status,
                Jsonb(state_object.payload),
                Jsonb(state_object.evidence_ids),
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
            SET title = %s, summary = %s, status = %s, payload = %s, evidence_ids = %s,
                version = %s, confidence = %s
            WHERE id = %s
            """,
            (
                state_object.title,
                state_object.summary,
                state_object.status,
                Jsonb(state_object.payload),
                Jsonb(state_object.evidence_ids),
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                change_event.id,
                change_event.workspace_id,
                change_event.record_id,
                change_event.change_type.value,
                change_event.summary,
                change_event.target_object_id,
                change_event.candidate_object_id,
                change_event.requires_review,
                Jsonb(change_event.evidence_ids),
                Jsonb(change_event.field_changes),
            ),
        )
        self.conn.commit()
        return change_event

    def list_state_objects(self, workspace_id: str) -> list[StateObject]:
        rows = self.conn.execute(
            "SELECT * FROM state_objects WHERE workspace_id = %s ORDER BY created_order",
            (workspace_id,),
        ).fetchall()
        return [state_object_from_row(row) for row in rows]

    def get_state_object(self, state_object_id: str) -> StateObject:
        row = self.conn.execute(
            "SELECT * FROM state_objects WHERE id = %s",
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
            "SELECT * FROM change_events WHERE workspace_id = %s ORDER BY created_order",
            (workspace_id,),
        ).fetchall()
        return [change_event_from_row(row) for row in rows]

    def save_record_digest(self, digest: RecordDigest | dict[str, Any]) -> dict[str, Any]:
        from recordflow_agent.serialization import to_jsonable

        digest_json = to_jsonable(digest)
        self.conn.execute(
            """
            INSERT INTO record_digests(record_id, workspace_id, digest_json, updated_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT(record_id)
            DO UPDATE SET workspace_id = excluded.workspace_id,
                          digest_json = excluded.digest_json,
                          updated_at = CURRENT_TIMESTAMP
            """,
            (
                digest_json["record_id"],
                digest_json["workspace_id"],
                Jsonb(digest_json),
            ),
        )
        self.conn.commit()
        return digest_json

    def get_record_digest(self, record_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT digest_json FROM record_digests WHERE record_id = %s",
            (record_id,),
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return row["digest_json"]

    def clear_all(self) -> None:
        self.conn.execute(
            """
            TRUNCATE TABLE
                media_records,
                record_digests,
                jobs,
                change_events,
                state_objects,
                topic_blocks,
                evidence_anchors,
                transcript_segments,
                records,
                workspaces,
                id_counters
            RESTART IDENTITY
            """
        )
        self.conn.commit()

    def list_review_items(self, workspace_id: str) -> list[ChangeEvent]:
        rows = self.conn.execute(
            """
            SELECT * FROM change_events
            WHERE workspace_id = %s AND requires_review = TRUE AND review_status = 'pending'
            ORDER BY created_order
            """,
            (workspace_id,),
        ).fetchall()
        return [change_event_from_row(row) for row in rows]

    def set_review_status(self, change_event_id: str, status: str) -> None:
        if status not in {"accepted", "ignored"}:
            raise ValueError("Review status must be accepted or ignored.")
        self.conn.execute(
            "UPDATE change_events SET review_status = %s WHERE id = %s",
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
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "process_record",
                "pending",
                Jsonb(
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                Jsonb([]),
                Jsonb({}),
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
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "transcribe_media",
                "pending",
                Jsonb(
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
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "prepare_site_task",
                "pending",
                Jsonb({"task_id": task_id}),
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
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "compress_media",
                "pending",
                Jsonb(
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
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "cleanup_expired_media",
                "pending",
                Jsonb({}),
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
            SET stored_name = %s,
                url = %s,
                public_url = %s,
                object_name = %s,
                content_type = %s,
                compressed_size_bytes = %s,
                compression_codec = %s,
                status = 'compressed',
                error = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
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
            SET status = %s,
                asr_task_id = COALESCE(%s, asr_task_id),
                transcript_text = COALESCE(%s, transcript_text),
                utterances = COALESCE(%s, utterances),
                raw_asr_result = COALESCE(%s, raw_asr_result),
                record_id = COALESCE(%s, record_id),
                error = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                status,
                asr_task_id,
                transcript_text,
                Jsonb(utterances) if utterances is not None else None,
                Jsonb(raw_asr_result) if raw_asr_result is not None else None,
                record_id,
                error,
                media_id,
            ),
        )
        self.conn.commit()

    def get_media_record(self, media_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM media_records WHERE id = %s", (media_id,)).fetchone()
        if row is None:
            raise KeyError(media_id)
        return media_record_from_row(row)

    def delete_media_record(self, media_id: str) -> None:
        deleted = self.conn.execute(
            "DELETE FROM media_records WHERE id = %s RETURNING id",
            (media_id,),
        ).fetchone()
        if deleted is None:
            raise KeyError(media_id)

    def list_media_records(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM media_records WHERE workspace_id = %s ORDER BY created_order",
            (workspace_id,),
        ).fetchall()
        return [media_record_from_row(row) for row in rows]

    def claim_next_job(self, job_types: set[str] | None = None) -> dict[str, Any] | None:
        with self.conn.transaction():
            if job_types:
                placeholders = ", ".join(["%s"] * len(job_types))
                row = self.conn.execute(
                    f"""
                    SELECT * FROM jobs
                    WHERE status = 'pending' AND type IN ({placeholders})
                    ORDER BY created_order
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    tuple(sorted(job_types)),
                ).fetchone()
            else:
                row = self.conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE status = 'pending'
                    ORDER BY created_order
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                ).fetchone()
            if row is None:
                return None
            self.conn.execute(
                "UPDATE jobs SET status = 'running', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (row["id"],),
            )
        return job_from_row(row) | {"status": "running"}

    def requeue_stale_running_jobs(self, max_age_seconds: int = 900) -> int:
        cursor = self.conn.execute(
            """
            UPDATE jobs
            SET status = 'pending',
                error = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
              AND updated_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
            """,
            (
                f"Requeued stale running job after {max_age_seconds} seconds.",
                max_age_seconds,
            ),
        )
        self.conn.commit()
        return cursor.rowcount

    def complete_job(self, job_id: str, record_id: str) -> None:
        self.conn.execute(
            """
            UPDATE jobs
            SET status = 'completed', record_id = %s, error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (record_id, job_id),
        )
        self.conn.commit()

    def fail_job(self, job_id: str, error: str) -> None:
        self.conn.execute(
            """
            UPDATE jobs
            SET status = 'failed', error = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (error, job_id),
        )
        self.conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return job_from_row(row)

    def reset_schema_for_tests(self) -> None:
        self.conn.execute(
            """
            DROP TABLE IF EXISTS media_records;
            DROP TABLE IF EXISTS record_digests;
            DROP TABLE IF EXISTS jobs;
            DROP TABLE IF EXISTS change_events;
            DROP TABLE IF EXISTS state_objects;
            DROP TABLE IF EXISTS topic_blocks;
            DROP TABLE IF EXISTS evidence_anchors;
            DROP TABLE IF EXISTS transcript_segments;
            DROP TABLE IF EXISTS records;
            DROP TABLE IF EXISTS workspaces;
            DROP TABLE IF EXISTS id_counters;
            """
        )
        self.conn.commit()
        self._init_schema()

    def _init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS id_counters(
                prefix TEXT PRIMARY KEY,
                next_value BIGINT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                profile TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records(
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                title TEXT NOT NULL,
                text TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transcript_segments(
                id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL REFERENCES records(id),
                text TEXT NOT NULL,
                speaker TEXT,
                start_time TEXT,
                end_time TEXT,
                confidence DOUBLE PRECISION NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_anchors(
                id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL REFERENCES records(id),
                segment_id TEXT NOT NULL REFERENCES transcript_segments(id),
                quote TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS topic_blocks(
                created_order BIGSERIAL,
                id TEXT PRIMARY KEY,
                record_id TEXT NOT NULL REFERENCES records(id),
                topic TEXT NOT NULL,
                summary TEXT NOT NULL,
                segment_ids JSONB NOT NULL,
                importance TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state_objects(
                created_order BIGSERIAL,
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                status TEXT NOT NULL,
                payload JSONB NOT NULL,
                evidence_ids JSONB NOT NULL,
                version INTEGER NOT NULL,
                confidence DOUBLE PRECISION NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS change_events(
                created_order BIGSERIAL,
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                record_id TEXT NOT NULL REFERENCES records(id),
                change_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                target_object_id TEXT,
                candidate_object_id TEXT NOT NULL,
                requires_review BOOLEAN NOT NULL,
                evidence_ids JSONB NOT NULL,
                field_changes JSONB NOT NULL,
                review_status TEXT NOT NULL DEFAULT 'pending'
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs(
                created_order BIGSERIAL,
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT NOT NULL,
                payload JSONB NOT NULL,
                record_id TEXT,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS record_digests(
                created_order BIGSERIAL,
                record_id TEXT PRIMARY KEY REFERENCES records(id),
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                digest_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS media_records(
                created_order BIGSERIAL,
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                source_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                url TEXT NOT NULL,
                public_url TEXT NOT NULL,
                object_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                original_size_bytes BIGINT,
                compressed_size_bytes BIGINT NOT NULL,
                compression_codec TEXT,
                status TEXT NOT NULL,
                asr_task_id TEXT,
                transcript_text TEXT,
                utterances JSONB NOT NULL,
                raw_asr_result JSONB NOT NULL,
                record_id TEXT,
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_created_order ON jobs(status, created_order)"
        )
        self.conn.commit()


class WorkspaceMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo

    def __getitem__(self, workspace_id: str) -> Workspace:
        row = self.repo.conn.execute(
            "SELECT * FROM workspaces WHERE id = %s",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise KeyError(workspace_id)
        return Workspace(id=row["id"], name=row["name"], profile=row["profile"])


class RecordMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo


class SegmentMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo

    def __getitem__(self, segment_id: str) -> TranscriptSegment:
        row = self.repo.conn.execute(
            "SELECT * FROM transcript_segments WHERE id = %s",
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
            "SELECT 1 FROM transcript_segments WHERE id = %s",
            (segment_id,),
        ).fetchone()
        return row is not None


class EvidenceMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo


class TopicBlockMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo


class StateObjectMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo


class ChangeEventMapping:
    def __init__(self, repo: PostgresRepository) -> None:
        self.repo = repo


def state_object_from_row(row: dict[str, Any]) -> StateObject:
    return StateObject(
        id=row["id"],
        workspace_id=row["workspace_id"],
        type=ObjectType(row["type"]),
        title=row["title"],
        summary=row["summary"],
        status=row["status"],
        payload=row["payload"],
        evidence_ids=row["evidence_ids"],
        version=row["version"],
        confidence=row["confidence"],
    )


def change_event_from_row(row: dict[str, Any]) -> ChangeEvent:
    return ChangeEvent(
        id=row["id"],
        workspace_id=row["workspace_id"],
        record_id=row["record_id"],
        change_type=ChangeType(row["change_type"]),
        summary=row["summary"],
        target_object_id=row["target_object_id"],
        candidate_object_id=row["candidate_object_id"],
        requires_review=bool(row["requires_review"]),
        evidence_ids=row["evidence_ids"],
        field_changes=row["field_changes"],
    )


def job_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "status": row["status"],
        "payload": row["payload"],
        "record_id": row["record_id"],
        "error": row["error"],
        "created_at": isoformat_or_value(row["created_at"]),
        "updated_at": isoformat_or_value(row["updated_at"]),
    }


def media_record_from_row(row: dict[str, Any]) -> dict[str, Any]:
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
        "utterances": row["utterances"],
        "raw_asr_result": row["raw_asr_result"],
        "record_id": row["record_id"],
        "error": row["error"],
        "created_at": isoformat_or_value(row["created_at"]),
        "updated_at": isoformat_or_value(row["updated_at"]),
    }


def isoformat_or_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
