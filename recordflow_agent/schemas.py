from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ObjectType(StrEnum):
    FACT = "Fact"
    DECISION = "Decision"
    TASK = "Task"
    QUESTION = "Question"
    RISK = "Risk"
    REQUIREMENT = "Requirement"
    OBJECTION = "Objection"
    IDEA = "Idea"
    INSIGHT = "Insight"
    KNOWLEDGE = "Knowledge"
    QUOTE = "Quote"
    TIMELINE_EVENT = "TimelineEvent"
    ENTITY = "Entity"


class ChangeType(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    CLOSE = "close"
    SUPERSEDE = "supersede"
    CLARIFY = "clarify"


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    profile: str


@dataclass(frozen=True)
class Record:
    id: str
    workspace_id: str
    title: str
    text: str


@dataclass(frozen=True)
class TranscriptSegment:
    id: str
    record_id: str
    text: str
    speaker: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class EvidenceAnchor:
    id: str
    record_id: str
    segment_id: str
    quote: str
    start_time: str | None = None
    end_time: str | None = None


@dataclass(frozen=True)
class TopicBlock:
    id: str
    record_id: str
    topic: str
    summary: str
    segment_ids: list[str]
    importance: str = "medium"


@dataclass
class CandidateObject:
    id: str
    type: ObjectType
    title: str
    summary: str
    payload: dict[str, Any]
    evidence_ids: list[str]
    topic_block_id: str
    confidence: float = 0.8


@dataclass
class StateObject:
    id: str
    workspace_id: str
    type: ObjectType
    title: str
    summary: str
    status: str
    payload: dict[str, Any]
    evidence_ids: list[str]
    version: int = 1
    confidence: float = 0.8


@dataclass(frozen=True)
class ChangeEvent:
    id: str
    workspace_id: str
    record_id: str
    change_type: ChangeType
    summary: str
    target_object_id: str | None
    candidate_object_id: str
    requires_review: bool
    evidence_ids: list[str]
    field_changes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordDigest:
    record_id: str
    workspace_id: str
    scene: str
    one_line_summary: str
    topic_blocks: list[TopicBlock]
    extracted_objects: list[CandidateObject]
    change_events: list[ChangeEvent]
    plan: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    evidence_index: list[dict[str, Any]] = field(default_factory=list)
    processing_trace: list[dict[str, Any]] = field(default_factory=list)
