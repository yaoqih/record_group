from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from recordflow_agent.serialization import to_jsonable


@dataclass(frozen=True)
class SkillSpec:
    name: str
    version: str
    description: str
    runner: Callable[..., Any]
    summarize_input: Callable[..., dict[str, Any]]
    summarize_output: Callable[[Any], dict[str, Any]]


@dataclass
class HarnessEvent:
    skill: str
    version: str
    status: str
    elapsed_ms: int
    input: dict[str, Any]
    output: dict[str, Any]
    error: str | None = None


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        self._skills[spec.name] = spec

    def get(self, name: str) -> SkillSpec:
        try:
            return self._skills[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._skills))
            raise KeyError(f"Unknown skill '{name}'. Available skills: {available}") from exc

    def list_names(self) -> list[str]:
        return sorted(self._skills)


class SkillHarness:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self.events: list[HarnessEvent] = []

    def run(self, skill_name: str, **kwargs: Any) -> Any:
        spec = self.registry.get(skill_name)
        started = perf_counter()
        try:
            output = spec.runner(**kwargs)
        except Exception as exc:
            self.events.append(
                HarnessEvent(
                    skill=spec.name,
                    version=spec.version,
                    status="error",
                    elapsed_ms=int((perf_counter() - started) * 1000),
                    input=spec.summarize_input(**kwargs),
                    output={},
                    error=str(exc),
                )
            )
            raise
        self.events.append(
            HarnessEvent(
                skill=spec.name,
                version=spec.version,
                status="ok",
                elapsed_ms=int((perf_counter() - started) * 1000),
                input=spec.summarize_input(**kwargs),
                output=spec.summarize_output(output),
            )
        )
        return output

    def trace(self) -> list[dict[str, Any]]:
        return [
            {
                "kind": "skill_harness",
                "skill": event.skill,
                "version": event.version,
                "status": event.status,
                "elapsed_ms": event.elapsed_ms,
                "input": to_jsonable(event.input),
                "output": to_jsonable(event.output),
                "error": event.error,
            }
            for event in self.events
        ]

    def trace_since(self, start_index: int) -> list[dict[str, Any]]:
        return [
            {
                "kind": "skill_harness",
                "skill": event.skill,
                "version": event.version,
                "status": event.status,
                "elapsed_ms": event.elapsed_ms,
                "input": to_jsonable(event.input),
                "output": to_jsonable(event.output),
                "error": event.error,
            }
            for event in self.events[start_index:]
        ]


def build_default_skill_registry() -> SkillRegistry:
    from recordflow_agent.skills import (
        extract_objects,
        merge_changes,
        render_digest,
        segment_topics,
    )

    registry = SkillRegistry()
    registry.register(
        SkillSpec(
            name="segment_topics",
            version="0.1",
            description="Split a record into topic blocks.",
            runner=segment_topics,
            summarize_input=lambda **kwargs: {
                "record_id": kwargs.get("record_id"),
                "segment_count": len(kwargs.get("segments", [])),
            },
            summarize_output=lambda output: {
                "topic_blocks": len(output),
            },
        )
    )
    registry.register(
        SkillSpec(
            name="extract_objects",
            version="0.1",
            description="Extract candidate structured objects from topic blocks.",
            runner=run_extraction_skill,
            summarize_input=lambda **kwargs: {
                "topic_block_count": len(kwargs.get("topic_blocks", [])),
                "profile": getattr(kwargs.get("profile"), "name", None),
                "extractor": type(kwargs.get("extractor")).__name__
                if kwargs.get("extractor") is not None
                else None,
            },
            summarize_output=lambda output: {
                "candidates": len(output),
            },
        )
    )
    registry.register(
        SkillSpec(
            name="merge_changes",
            version="0.1",
            description="Merge candidate objects into the current state.",
            runner=merge_changes,
            summarize_input=lambda **kwargs: {
                "workspace_id": kwargs.get("workspace_id"),
                "candidate_count": len(kwargs.get("candidates", [])),
            },
            summarize_output=lambda output: {
                "changes": len(output),
            },
        )
    )
    registry.register(
        SkillSpec(
            name="render_digest",
            version="0.1",
            description="Render a hierarchical digest from topic blocks, candidates and changes.",
            runner=render_digest,
            summarize_input=lambda **kwargs: {
                "workspace_id": kwargs.get("workspace_id"),
                "topic_block_count": len(kwargs.get("topic_blocks", [])),
                "candidate_count": len(kwargs.get("candidates", [])),
                "change_count": len(kwargs.get("changes", [])),
                "digest_renderer": type(kwargs.get("digest_renderer")).__name__
                if kwargs.get("digest_renderer") is not None
                else None,
            },
            summarize_output=lambda output: {
                "sections": len(output.sections),
                "evidence_index": len(output.evidence_index),
            },
        )
    )
    return registry


def build_default_skill_harness() -> SkillHarness:
    return SkillHarness(build_default_skill_registry())


def run_extraction_skill(**kwargs: Any) -> Any:
    extractor = kwargs.pop("extractor", None)
    if extractor is not None:
        return extractor.extract(
            kwargs["repo"],
            kwargs["profile"],
            kwargs["topic_blocks"],
        )
    from recordflow_agent.skills import extract_objects

    return extract_objects(**kwargs)
