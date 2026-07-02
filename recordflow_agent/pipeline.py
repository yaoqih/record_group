from __future__ import annotations

from recordflow_agent.harness import SkillHarness, build_default_skill_harness
from recordflow_agent.profiles import SceneProfile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.schemas import CandidateObject, RecordDigest, TopicBlock
from recordflow_agent.skills import (
    normalize_sentences,
    normalize_segments,
)


def process_record(
    repo: InMemoryRepository,
    workspace_id: str,
    profile: SceneProfile,
    title: str,
    text: str,
    extractor: object | None = None,
    digest_renderer: object | None = None,
    harness: SkillHarness | None = None,
) -> RecordDigest:
    active_harness = harness or build_default_skill_harness()
    trace_start_index = len(active_harness.events)
    record = repo.add_record(workspace_id=workspace_id, title=title, text=text)
    segments = [
        repo.add_segment(record_id=record.id, text=sentence)
        for sentence in normalize_segments(text)
    ]
    topic_blocks = active_harness.run(
        "segment_topics",
        repo=repo,
        record_id=record.id,
        segments=segments,
    )
    candidates = active_harness.run(
        "extract_objects",
        repo=repo,
        profile=profile,
        topic_blocks=topic_blocks,
        extractor=extractor,
    )
    changes = active_harness.run(
        "merge_changes",
        repo=repo,
        workspace_id=workspace_id,
        record_id=record.id,
        candidates=candidates,
    )
    digest = active_harness.run(
        "render_digest",
        record_id=record.id,
        workspace_id=workspace_id,
        scene=profile.name,
        source_text=text,
        topic_blocks=topic_blocks,
        candidates=candidates,
        changes=changes,
        digest_renderer=digest_renderer,
    )
    digest.processing_trace.extend(active_harness.trace_since(trace_start_index))
    if hasattr(repo, "save_record_digest"):
        repo.save_record_digest(digest)
    return digest


def run_extractor(
    repo: InMemoryRepository,
    profile: SceneProfile,
    topic_blocks: list[TopicBlock],
    extractor: object | None,
) -> list[CandidateObject]:
    if extractor is None:
        from recordflow_agent.skills import extract_objects

        return extract_objects(repo=repo, profile=profile, topic_blocks=topic_blocks)
    return extractor.extract(repo, profile, topic_blocks)
