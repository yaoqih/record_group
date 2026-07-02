from __future__ import annotations

from collections import defaultdict
from itertools import count
from typing import Any

from recordflow_agent.schemas import (
    ChangeEvent,
    ChangeType,
    EvidenceAnchor,
    RecordDigest,
    Record,
    StateObject,
    TopicBlock,
    TranscriptSegment,
    Workspace,
)


class InMemoryRepository:
    def __init__(self) -> None:
        self._counter = count(1)
        self.workspaces: dict[str, Workspace] = {}
        self.records: dict[str, Record] = {}
        self.segments: dict[str, TranscriptSegment] = {}
        self.evidence: dict[str, EvidenceAnchor] = {}
        self.topic_blocks: dict[str, TopicBlock] = {}
        self.state_objects: dict[str, StateObject] = {}
        self.change_events: dict[str, ChangeEvent] = {}
        self.record_digests: dict[str, dict[str, Any]] = {}
        self.workspace_objects: dict[str, list[str]] = defaultdict(list)
        self.workspace_changes: dict[str, list[str]] = defaultdict(list)

    def next_id(self, prefix: str) -> str:
        return f"{prefix}_{next(self._counter):06d}"

    def create_workspace(self, name: str, profile: str) -> str:
        workspace_id = self.next_id("ws")
        self.workspaces[workspace_id] = Workspace(
            id=workspace_id,
            name=name,
            profile=profile,
        )
        return workspace_id

    def list_workspaces(self) -> list[Workspace]:
        return list(self.workspaces.values())

    def add_record(self, workspace_id: str, title: str, text: str) -> Record:
        record = Record(
            id=self.next_id("rec"),
            workspace_id=workspace_id,
            title=title,
            text=text,
        )
        self.records[record.id] = record
        return record

    def list_records(self, workspace_id: str | None = None) -> list[Record]:
        records = list(self.records.values())
        if workspace_id is None:
            return records
        return [record for record in records if record.workspace_id == workspace_id]

    def add_segment(self, record_id: str, text: str) -> TranscriptSegment:
        segment = TranscriptSegment(
            id=self.next_id("seg"),
            record_id=record_id,
            text=text,
        )
        self.segments[segment.id] = segment
        return segment

    def add_evidence(self, record_id: str, segment_id: str, quote: str) -> EvidenceAnchor:
        evidence = EvidenceAnchor(
            id=self.next_id("ev"),
            record_id=record_id,
            segment_id=segment_id,
            quote=quote,
        )
        self.evidence[evidence.id] = evidence
        return evidence

    def add_topic_block(self, topic_block: TopicBlock) -> TopicBlock:
        self.topic_blocks[topic_block.id] = topic_block
        return topic_block

    def add_state_object(self, state_object: StateObject) -> StateObject:
        self.state_objects[state_object.id] = state_object
        self.workspace_objects[state_object.workspace_id].append(state_object.id)
        return state_object

    def update_state_object(self, state_object: StateObject) -> StateObject:
        state_object.version += 1
        self.state_objects[state_object.id] = state_object
        return state_object

    def add_change_event(self, change_event: ChangeEvent) -> ChangeEvent:
        self.change_events[change_event.id] = change_event
        self.workspace_changes[change_event.workspace_id].append(change_event.id)
        return change_event

    def list_state_objects(self, workspace_id: str) -> list[StateObject]:
        return [
            self.state_objects[object_id]
            for object_id in self.workspace_objects.get(workspace_id, [])
        ]

    def list_change_events(self, workspace_id: str) -> list[ChangeEvent]:
        return [
            self.change_events[change_id]
            for change_id in self.workspace_changes.get(workspace_id, [])
        ]

    def save_record_digest(self, digest: RecordDigest | dict[str, Any]) -> dict[str, Any]:
        from recordflow_agent.serialization import to_jsonable

        digest_json = to_jsonable(digest)
        self.record_digests[digest_json["record_id"]] = digest_json
        return digest_json

    def get_record_digest(self, record_id: str) -> dict[str, Any]:
        try:
            return self.record_digests[record_id]
        except KeyError as exc:
            raise KeyError(record_id) from exc

    def clear_all(self) -> None:
        self.__init__()

    def get_state_object(self, state_object_id: str) -> StateObject:
        try:
            return self.state_objects[state_object_id]
        except KeyError as exc:
            raise KeyError(state_object_id) from exc

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
        return state_object, self.add_change_event(change)
