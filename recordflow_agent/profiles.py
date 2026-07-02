from __future__ import annotations

from dataclasses import dataclass

from recordflow_agent.schemas import ObjectType


@dataclass(frozen=True)
class SceneProfile:
    name: str
    display_name: str
    enabled_objects: tuple[ObjectType, ...]
    review_rules: dict[str, str]
    outputs: tuple[str, ...]


PROFILES: dict[str, SceneProfile] = {
    "transcribe_proofread": SceneProfile(
        name="transcribe_proofread",
        display_name="转录和校对",
        enabled_objects=tuple(ObjectType),
        review_rules={
            ObjectType.DECISION.value: "always_review",
            ObjectType.RISK.value: "review_if_open",
            ObjectType.INSIGHT.value: "review_if_low_confidence",
            ObjectType.OBJECTION.value: "review",
        },
        outputs=("proofread_digest", "state_objects", "change_review"),
    ),
    "detailed_summary": SceneProfile(
        name="detailed_summary",
        display_name="详细整理和总结",
        enabled_objects=(
            ObjectType.DECISION,
            ObjectType.TASK,
            ObjectType.QUESTION,
            ObjectType.RISK,
            ObjectType.FACT,
            ObjectType.QUOTE,
            ObjectType.REQUIREMENT,
            ObjectType.OBJECTION,
            ObjectType.IDEA,
            ObjectType.INSIGHT,
            ObjectType.KNOWLEDGE,
            ObjectType.TIMELINE_EVENT,
            ObjectType.ENTITY,
        ),
        review_rules={
            ObjectType.DECISION.value: "always_review",
            "Task.due_date_changed": "review",
            ObjectType.RISK.value: "review_if_high",
            ObjectType.FACT.value: "auto_accept",
        },
        outputs=("record_digest", "change_review"),
    ),
}

PROFILE_ALIASES: dict[str, str] = {
    "general_record": "transcribe_proofread",
    "project_meeting": "detailed_summary",
    "customer_followup": "detailed_summary",
    "user_research": "detailed_summary",
}


def load_profile(name: str) -> SceneProfile:
    canonical_name = PROFILE_ALIASES.get(name, name)
    try:
        return PROFILES[canonical_name]
    except KeyError as exc:
        available = ", ".join(sorted(PROFILES))
        raise ValueError(f"Unknown profile '{name}'. Available profiles: {available}") from exc
