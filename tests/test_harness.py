import pytest

from recordflow_agent.harness import (
    SkillHarness,
    SkillRegistry,
    SkillSpec,
    build_default_skill_registry,
)


def test_default_skill_registry_exposes_pipeline_skills():
    registry = build_default_skill_registry()

    assert registry.list_names() == [
        "extract_objects",
        "merge_changes",
        "render_digest",
        "segment_topics",
    ]


def test_skill_harness_records_success_event():
    registry = SkillRegistry()
    registry.register(
        SkillSpec(
            name="double",
            version="0.1",
            description="Double an integer.",
            runner=lambda value: value * 2,
            summarize_input=lambda **kwargs: {"value": kwargs["value"]},
            summarize_output=lambda output: {"result": output},
        )
    )
    harness = SkillHarness(registry)

    result = harness.run("double", value=21)

    assert result == 42
    assert len(harness.events) == 1
    event = harness.events[0]
    assert event.skill == "double"
    assert event.version == "0.1"
    assert event.status == "ok"
    assert event.input == {"value": 21}
    assert event.output == {"result": 42}
    assert event.error is None
    assert event.elapsed_ms >= 0


def test_skill_harness_records_error_event_before_reraising():
    def fail_skill(value):
        raise ValueError(f"bad value: {value}")

    registry = SkillRegistry()
    registry.register(
        SkillSpec(
            name="fail",
            version="0.1",
            description="Always fail.",
            runner=fail_skill,
            summarize_input=lambda **kwargs: {"value": kwargs["value"]},
            summarize_output=lambda output: {"unused": output},
        )
    )
    harness = SkillHarness(registry)

    with pytest.raises(ValueError, match="bad value: 7"):
        harness.run("fail", value=7)

    assert len(harness.events) == 1
    event = harness.events[0]
    assert event.skill == "fail"
    assert event.status == "error"
    assert event.input == {"value": 7}
    assert event.output == {}
    assert event.error == "bad value: 7"
