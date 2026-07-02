from recordflow_agent.llm_skills import LLMDigestRenderer, LLMExtractor
from recordflow_agent.profiles import load_profile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.schemas import CandidateObject, ObjectType, TopicBlock


class FakeJSONClient:
    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
        return {
            "items": [
                {
                    "type": "Task",
                    "title": "后端",
                    "summary": "张三负责后端，周五前完成",
                    "payload": {
                        "owner": "张三",
                        "action": "后端",
                        "due_date": "周五前",
                    },
                    "evidence_segment_ids": ["seg_001"],
                    "confidence": 0.9,
                }
            ]
        }


def test_llm_extractor_converts_json_response_to_candidates():
    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    record = repo.add_record(workspace_id, "meeting", "张三负责后端，周五前完成")
    segment = repo.add_segment(record.id, "张三负责后端，周五前完成")
    topic_block = repo.add_topic_block(
        TopicBlock(
            id="topic_001",
            record_id=record.id,
            topic="任务推进",
            summary=segment.text,
            segment_ids=[segment.id],
        )
    )

    extractor = LLMExtractor(FakeJSONClient())
    candidates = extractor.extract(repo, profile, [topic_block])

    assert len(candidates) == 1
    assert candidates[0].type == ObjectType.TASK
    assert candidates[0].payload["due_date"] == "周五前"
    assert candidates[0].evidence_ids


def test_llm_extractor_falls_back_to_rule_payload_when_model_payload_is_empty():
    class EmptyPayloadClient:
        def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            return {
                "items": [
                    {
                        "type": "Task",
                        "title": "后端开发",
                        "summary": "张三负责后端，周五前完成",
                        "payload": {},
                        "evidence_segment_ids": [],
                        "confidence": 0.8,
                    }
                ]
            }

    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    record = repo.add_record(workspace_id, "meeting", "张三负责后端，周五前完成")
    segment = repo.add_segment(record.id, "张三负责后端，周五前完成")
    topic_block = repo.add_topic_block(
        TopicBlock(
            id="topic_001",
            record_id=record.id,
            topic="任务推进",
            summary=segment.text,
            segment_ids=[segment.id],
        )
    )

    extractor = LLMExtractor(EmptyPayloadClient())
    candidates = extractor.extract(repo, profile, [topic_block])

    assert candidates[0].payload["action"] == "后端"
    assert candidates[0].payload["due_date"] == "周五前"


def test_llm_extractor_falls_back_to_rules_when_client_fails():
    class FailingClient:
        def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            raise TimeoutError("LLM request timed out")

    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    record = repo.add_record(workspace_id, "meeting", "张三负责后端，周五前完成")
    segment = repo.add_segment(record.id, "张三负责后端，周五前完成")
    topic_block = repo.add_topic_block(
        TopicBlock(
            id="topic_001",
            record_id=record.id,
            topic="任务推进",
            summary=segment.text,
            segment_ids=[segment.id],
        )
    )

    extractor = LLMExtractor(FailingClient())
    candidates = extractor.extract(repo, profile, [topic_block])

    assert len(candidates) == 1
    assert candidates[0].type == ObjectType.TASK
    assert candidates[0].payload["action"] == "后端"


def test_llm_extractor_stops_calling_client_after_first_failure():
    class FailingClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            self.calls += 1
            raise TimeoutError("LLM request timed out")

    repo = InMemoryRepository()
    profile = load_profile("project_meeting")
    workspace_id = repo.create_workspace("RecordFlow product", profile.name)
    record = repo.add_record(
        workspace_id,
        "meeting",
        "We decided the target group. There is a risk that LCD will increase cost.",
    )
    first_segment = repo.add_segment(record.id, "We decided the target group.")
    second_segment = repo.add_segment(record.id, "There is a risk that LCD will increase cost.")
    topic_blocks = [
        repo.add_topic_block(
            TopicBlock(
                id="topic_001",
                record_id=record.id,
                topic="决策",
                summary=first_segment.text,
                segment_ids=[first_segment.id],
            )
        ),
        repo.add_topic_block(
            TopicBlock(
                id="topic_002",
                record_id=record.id,
                topic="风险",
                summary=second_segment.text,
                segment_ids=[second_segment.id],
            )
        ),
    ]

    client = FailingClient()
    extractor = LLMExtractor(client)
    candidates = extractor.extract(repo, profile, topic_blocks)

    assert client.calls == 1
    assert {candidate.type for candidate in candidates} >= {ObjectType.DECISION, ObjectType.RISK}


def test_llm_digest_renderer_updates_section_content_and_preserves_evidence():
    class RecordingDigestClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            self.calls.append({"system": system_prompt, "user": user_prompt})
            if len(self.calls) == 1:
                assert "顶层大纲规划器" in system_prompt
                assert "完整文本" in system_prompt
                assert "第一段总览。第二段细节。" in user_prompt
                return {
                    "levels": ["chapter", "section"],
                    "outline": [
                        {
                            "id": "outline_chapter_001",
                            "level": "chapter",
                            "title": "整体进展",
                            "purpose": "先总后分。",
                            "topic_block_ids": ["topic_001", "topic_002"],
                            "children": [
                                {
                                    "id": "outline_section_001",
                                    "level": "section",
                                    "title": "第一段",
                                    "purpose": "写第一段。",
                                    "topic_block_ids": ["topic_001"],
                                    "children": [],
                                },
                                {
                                    "id": "outline_section_002",
                                    "level": "section",
                                    "title": "第二段",
                                    "purpose": "写第二段。",
                                    "topic_block_ids": ["topic_002"],
                                    "children": [],
                                },
                            ],
                        }
                    ],
                }
            assert "章节写作器" in system_prompt
            assert "outline_path" in user_prompt
            if len(self.calls) == 2:
                return {
                    "title": "第一段",
                    "summary": "LLM 生成的第一段摘要。",
                    "detailed_summary": "LLM 生成的第一段更详细摘要。",
                    "key_points": ["保留原始证据锚点。"],
                }
            return {
                "title": "第二段",
                "summary": "LLM 生成的第二段摘要。",
                "detailed_summary": "LLM 生成的第二段更详细摘要。",
                "key_points": ["保留第二段证据锚点。"],
            }

    client = RecordingDigestClient()
    topic_block_1 = TopicBlock(
        id="topic_001",
        record_id="rec_001",
        topic="任务推进",
        summary="第一段总览。",
        segment_ids=["seg_001"],
        importance="high",
    )
    topic_block_2 = TopicBlock(
        id="topic_002",
        record_id="rec_001",
        topic="风险",
        summary="第二段细节。",
        segment_ids=["seg_002"],
        importance="medium",
    )
    candidate = CandidateObject(
        id="cand_001",
        type=ObjectType.TASK,
        title="send interface notes",
        summary=topic_block_1.summary,
        payload={"owner": "Sarah"},
        evidence_ids=["ev_001"],
        topic_block_id=topic_block_1.id,
    )

    renderer = LLMDigestRenderer(client)
    source_text = "第一段总览。第二段细节。" * 120
    digest = renderer.render(
        record_id="rec_001",
        workspace_id="ws_001",
        scene="project_meeting",
        source_text=source_text,
        topic_blocks=[topic_block_1, topic_block_2],
        candidates=[candidate],
        changes=[],
    )

    assert len(client.calls) == 3
    assert digest.plan["engine"] == "llm_top_down_digest_v1"
    assert digest.plan["llm_outline"]["status"] == "applied"
    assert digest.plan["levels"] == ["chapter", "section"]
    assert len(digest.sections) == 2
    assert digest.sections[0]["summary"] == "LLM 生成的第一段摘要。"
    assert digest.sections[0]["detailed_summary"] == "LLM 生成的第一段更详细摘要。"
    assert digest.sections[0]["key_points"] == ["保留原始证据锚点。"]
    assert digest.sections[0]["evidence_segment_ids"] == ["seg_001"]
    assert digest.sections[1]["summary"] == "LLM 生成的第二段摘要。"
    assert digest.sections[1]["evidence_segment_ids"] == ["seg_002"]


def test_llm_digest_renderer_falls_back_to_deterministic_digest_when_client_fails():
    class FailingDigestClient:
        def __init__(self) -> None:
            self.calls = 0

        def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.0):
            self.calls += 1
            raise TimeoutError("LLM request timed out")

    topic_block = TopicBlock(
        id="topic_001",
        record_id="rec_001",
        topic="任务推进",
        summary="Sarah is responsible for sending interface notes by Friday.",
        segment_ids=["seg_001"],
        importance="high",
    )

    renderer = LLMDigestRenderer(FailingDigestClient())
    digest = renderer.render(
        record_id="rec_001",
        workspace_id="ws_001",
        scene="project_meeting",
        source_text=topic_block.summary,
        topic_blocks=[topic_block],
        candidates=[],
        changes=[],
    )

    assert digest.plan["llm_digest"]["status"] == "fallback"
    assert "LLM request timed out" in digest.plan["llm_digest"]["error"]
    assert digest.sections[0]["evidence_segment_ids"] == ["seg_001"]
