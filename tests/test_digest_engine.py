import pytest

from recordflow_agent.digest_engine import (
    apply_digest_patch_json,
    choose_digest_levels,
    render_top_down_digest,
)
from recordflow_agent.schemas import CandidateObject, ChangeEvent, ChangeType, ObjectType, TopicBlock
from recordflow_agent.serialization import to_jsonable


def test_choose_digest_levels_uses_source_character_count():
    assert choose_digest_levels({"character_count": 1200}) == ["section"]
    assert choose_digest_levels({"character_count": 1201}) == ["chapter", "section"]
    assert choose_digest_levels({"character_count": 4501}) == ["part", "chapter", "section"]


def test_digest_patch_json_preserves_objects_and_change_events():
    topic_block = TopicBlock(
        id="topic_001",
        record_id="rec_001",
        topic="任务推进",
        summary="Sarah is responsible for sending interface notes by Friday.",
        segment_ids=["seg_001"],
        importance="high",
    )
    candidate = CandidateObject(
        id="cand_001",
        type=ObjectType.TASK,
        title="send interface notes",
        summary=topic_block.summary,
        payload={"owner": "Sarah", "action": "send interface notes", "due_date": "Friday"},
        evidence_ids=["ev_001"],
        topic_block_id=topic_block.id,
        confidence=0.91,
    )
    change = ChangeEvent(
        id="chg_001",
        workspace_id="ws_001",
        record_id="rec_001",
        change_type=ChangeType.CREATE,
        summary="Created Task: send interface notes",
        target_object_id="state_001",
        candidate_object_id=candidate.id,
        requires_review=True,
        evidence_ids=["ev_001"],
        field_changes={},
    )
    digest = render_top_down_digest(
        record_id="rec_001",
        workspace_id="ws_001",
        scene="project_meeting",
        source_text=topic_block.summary,
        topic_blocks=[topic_block],
        candidates=[candidate],
        changes=[change],
    )

    patched = apply_digest_patch_json(
        to_jsonable(digest),
        {
            "op": "mark_uncertain",
            "section_id": digest.sections[0]["id"],
            "reason": "用户认为这里需要复核。",
        },
    )

    assert patched["extracted_objects"][0]["id"] == "cand_001"
    assert patched["change_events"][0]["id"] == "chg_001"
    assert patched["extracted_objects"][0]["type"] == "Task"
    assert patched["change_events"][0]["change_type"] == "create"
    assert patched["sections"][0]["uncertainty"] == "用户认为这里需要复核。"


def test_digest_patch_json_rejects_missing_section():
    digest = {
        "record_id": "rec_001",
        "workspace_id": "ws_001",
        "scene": "project_meeting",
        "one_line_summary": "",
        "topic_blocks": [],
        "extracted_objects": [],
        "change_events": [],
        "sections": [],
    }

    with pytest.raises(KeyError, match="missing"):
        apply_digest_patch_json(
            digest,
            {"op": "insert_key_point", "section_id": "missing", "text": "补充"},
        )
