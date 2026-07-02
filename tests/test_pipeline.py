from recordflow_agent.digest_engine import apply_digest_patch
from recordflow_agent.harness import build_default_skill_harness
from recordflow_agent.pipeline import process_record
from recordflow_agent.profiles import load_profile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.schemas import ChangeType, ObjectType


def test_process_first_project_meeting_creates_digest_objects_and_state():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。风险是音频上传会拖慢进度。",
    )

    objects = repo.list_state_objects(workspace_id)
    changes = repo.list_change_events(workspace_id)

    assert digest.one_line_summary
    assert len(digest.topic_blocks) >= 1
    assert {obj.type for obj in objects} >= {
        ObjectType.DECISION,
        ObjectType.TASK,
        ObjectType.RISK,
    }
    assert all(change.change_type == ChangeType.CREATE for change in changes)
    assert all(obj.evidence_ids for obj in objects)


def test_process_record_only_writes_evidence_for_extracted_objects():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting",
        text="大家先寒暄了一下。张三负责后端，周五前完成。",
    )

    assert len(digest.extracted_objects) == 1
    assert len(repo.evidence) == 1


def test_process_long_record_caps_persisted_topic_blocks():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    neutral = "The team briefly discussed background context."
    text = " ".join(
        [neutral] * 160
        + [
            "We decided to keep the target group simple.",
            "There is a risk that the LCD display will increase cost.",
            "Sarah is responsible for sending interface notes by Friday.",
        ]
    )

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="long meeting",
        text=text,
    )

    assert len(digest.topic_blocks) <= 80
    assert len(repo.segments) <= 80
    assert {candidate.type for candidate in digest.extracted_objects} >= {
        ObjectType.DECISION,
        ObjectType.RISK,
        ObjectType.TASK,
    }


def test_process_long_record_builds_top_down_digest_sections():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    text = " ".join(
        [
            "The meeting starts by reviewing the agenda and the previous target group decision.",
            "The team discusses materials for the remote control case including plastic, titanium, rubber and latex.",
            "They consider interface options including push buttons, scroll wheels and an LCD screen.",
            "There is a risk that the LCD display will increase cost.",
            "Sarah is responsible for sending interface notes by Friday.",
        ]
        * 20
    )

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="long meeting",
        text=text,
    )

    assert digest.plan["engine"] == "top_down_digest_v1"
    assert digest.plan["levels"] in (["chapter", "section"], ["part", "chapter", "section"])
    assert len(digest.sections) >= 3
    assert all(section["title"] for section in digest.sections)
    assert all(section["evidence_segment_ids"] for section in digest.sections)
    assert digest.evidence_index


def test_long_record_digest_has_top_down_outline_and_reconcile_report():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    text = " ".join(
        [
            "The meeting opens with agenda review and user needs.",
            "The team discusses target users, remote control constraints, and product assumptions.",
            "We decided to keep the first prototype focused on text import.",
            "Sarah is responsible for writing interface notes by Friday.",
            "There is a risk that LCD display work will increase cost.",
            "The group leaves battery sourcing as an open question?",
        ]
        * 18
    )

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="real digest engine meeting",
        text=text,
    )

    assert digest.plan["engine"] == "top_down_digest_v1"
    assert digest.plan["levels"] == ["part", "chapter", "section"]
    assert digest.plan["source_stats"]["segment_count"] == len(digest.topic_blocks)
    assert digest.plan["outline"]
    assert all(node["children"] for node in digest.plan["outline"])
    assert all(section["outline_path"] for section in digest.sections)
    assert all(section["evidence_span"]["segment_ids"] for section in digest.sections)
    assert all("detailed_summary" in section for section in digest.sections)
    assert digest.plan["coverage"]["covered_segment_count"] == len(digest.topic_blocks)
    assert digest.plan["reconcile"]["status"] == "ok"
    assert digest.plan["patch_contract"]["operations"] == [
        "replace_section",
        "insert_key_point",
        "split_section",
        "mark_uncertain",
    ]


def test_short_record_with_many_tiny_segments_stays_single_level():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    text = " ".join(["A."] * 24)

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="short meeting",
        text=text,
    )

    assert digest.plan["levels"] == ["section"]
    assert digest.plan["source_stats"]["character_count"] == len(text)


def test_digest_patch_replaces_one_section_without_losing_evidence():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="patchable meeting",
        text=(
            "We decided to keep the target group simple. "
            "Sarah is responsible for sending interface notes by Friday. "
            "There is a risk that LCD display will increase cost."
        ),
    )
    first_section = digest.sections[0]

    patched = apply_digest_patch(
        digest,
        {
            "op": "replace_section",
            "section_id": first_section["id"],
            "summary": "用户确认后的章节摘要，只改写这一节。",
            "key_points": ["保留原始证据，只替换展示摘要。"],
        },
    )

    patched_section = next(section for section in patched.sections if section["id"] == first_section["id"])
    untouched = [section for section in patched.sections if section["id"] != first_section["id"]]

    assert patched_section["summary"] == "用户确认后的章节摘要，只改写这一节。"
    assert patched_section["key_points"] == ["保留原始证据，只替换展示摘要。"]
    assert patched_section["evidence_segment_ids"] == first_section["evidence_segment_ids"]
    assert patched_section["patch_history"][-1]["op"] == "replace_section"
    assert all("patch_history" not in section for section in untouched)


def test_process_record_with_harness_adds_skill_trace_to_digest():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    harness = build_default_skill_harness()

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
        harness=harness,
    )

    harness_trace = [
        event for event in digest.processing_trace if event.get("kind") == "skill_harness"
    ]

    assert [event["skill"] for event in harness_trace] == [
        "segment_topics",
        "extract_objects",
        "merge_changes",
        "render_digest",
    ]
    assert all(event["status"] == "ok" for event in harness_trace)
    assert harness_trace[-1]["output"]["sections"] == len(digest.sections)


def test_reused_harness_only_adds_current_record_trace_to_digest():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    harness = build_default_skill_harness()

    first_digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
        harness=harness,
    )
    second_digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 2",
        text="新增 Review Queue。风险是上传任务可能阻塞。",
        harness=harness,
    )

    first_trace = [
        event for event in first_digest.processing_trace if event.get("kind") == "skill_harness"
    ]
    second_trace = [
        event for event in second_digest.processing_trace if event.get("kind") == "skill_harness"
    ]

    assert len(harness.events) == 8
    assert [event["skill"] for event in first_trace] == [
        "segment_topics",
        "extract_objects",
        "merge_changes",
        "render_digest",
    ]
    assert [event["skill"] for event in second_trace] == [
        "segment_topics",
        "extract_objects",
        "merge_changes",
        "render_digest",
    ]


def test_process_followup_updates_existing_task_due_date_instead_of_duplicate():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)

    process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="决定先做文本导入 MVP。张三负责后端，周五前完成。",
    )
    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 2",
        text="后端截止时间不用周五了，提前到周三下班前完成。新增 Review Queue。",
    )

    tasks = [
        obj for obj in repo.list_state_objects(workspace_id) if obj.type == ObjectType.TASK
    ]
    task_changes = [
        change
        for change in repo.list_change_events(workspace_id)
        if change.target_object_id in {task.id for task in tasks}
    ]

    backend_tasks = [task for task in tasks if task.payload["action"] == "后端"]
    review_tasks = [task for task in tasks if task.payload["action"] == "Review Queue"]

    assert len(backend_tasks) == 1
    assert len(review_tasks) == 1
    assert backend_tasks[0].payload["due_date"] == "周三下班前"
    assert any(change.change_type == ChangeType.UPDATE for change in task_changes)
    assert any(change.change_type == ChangeType.CREATE for change in digest.change_events)


def test_process_real_customer_followup_transcript_extracts_requirement():
    repo = InMemoryRepository()
    profile = load_profile("customer_followup")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    text = (
        "客户说希望和配偶一起开一个联名账户。"
        "她还问是否需要双方都到场，以及后续开户流程怎么安排。"
    )

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="real customer followup",
        text=text,
    )

    assert any(candidate.type == ObjectType.REQUIREMENT for candidate in digest.extracted_objects)
    assert any(obj.type == ObjectType.REQUIREMENT for obj in repo.list_state_objects(workspace_id))


def test_general_record_extracts_all_state_object_types():
    repo = InMemoryRepository()
    profile = load_profile("general_record")
    workspace_id = repo.create_workspace("RecordFlow general", profile.name)

    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="mixed meeting",
        text=(
            "事实：客户目前使用本地部署系统。"
            "决定：下周先做小范围试点。"
            "任务：王工周五前提供接口文档。"
            "问题：数据权限由谁审批？"
            "风险：历史数据质量不稳定。"
            "需求：希望支持批量导入录音。"
            "异议：客户担心部署成本过高。"
            "想法：可以把录音整理成主题状态页。"
            "洞察：用户真正需要的是状态更新。"
            "知识：增量合并需要保留变更历史。"
            "原话：「这个状态页比普通纪要更有用」。"
            "时间线：4月30日完成方案评审。"
            "实体：李工来自A公司，产品叫RecordFlow。"
        ),
    )

    object_types = {candidate.type for candidate in digest.extracted_objects}
    state_types = {state_object.type for state_object in repo.list_state_objects(workspace_id)}

    assert object_types == set(ObjectType)
    assert state_types == set(ObjectType)
    assert all(candidate.payload.get("merge_key") for candidate in digest.extracted_objects)
    assert all(candidate.evidence_ids for candidate in digest.extracted_objects)
    assert digest.plan["object_counts"]["Task"] == 1
    assert any(section["object_counts"].get("Entity") == 1 for section in digest.sections)


def test_general_record_incrementally_updates_and_closes_state_objects():
    repo = InMemoryRepository()
    profile = load_profile("general_record")
    workspace_id = repo.create_workspace("RecordFlow general", profile.name)

    process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 1",
        text="任务：王工周五前提供接口文档。风险：历史数据质量不稳定。",
    )
    digest = process_record(
        repo=repo,
        workspace_id=workspace_id,
        profile=profile,
        title="meeting 2",
        text="任务：王工周三前提供接口文档。风险已解决：历史数据质量不稳定。",
    )

    tasks = [
        obj for obj in repo.list_state_objects(workspace_id) if obj.type == ObjectType.TASK
    ]
    risks = [
        obj for obj in repo.list_state_objects(workspace_id) if obj.type == ObjectType.RISK
    ]

    assert len(tasks) == 1
    assert tasks[0].payload["due_date"] == "周三前"
    assert len(risks) == 1
    assert risks[0].status == "closed"
    assert any(change.change_type == ChangeType.UPDATE for change in digest.change_events)
    assert any(change.change_type == ChangeType.CLOSE for change in digest.change_events)
