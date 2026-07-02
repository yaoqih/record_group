from __future__ import annotations

import json
from typing import Protocol

from recordflow_agent.digest_engine import (
    build_coverage_report,
    build_detailed_summary,
    build_digest_evidence_index,
    build_key_points,
    build_one_line_summary,
    build_source_stats,
    choose_digest_levels,
    count_candidates_by_type,
    count_outline_nodes,
    iter_leaf_outline_nodes,
    reconcile_digest_sections,
    render_top_down_digest,
    summarize_topic_group,
    unique_segment_ids,
)
from recordflow_agent.profiles import SceneProfile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.schemas import CandidateObject, ChangeEvent, ObjectType, RecordDigest, TopicBlock
from recordflow_agent.skills import infer_objects


class JSONChatClient(Protocol):
    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> dict:
        ...


class LLMExtractor:
    def __init__(self, client: JSONChatClient) -> None:
        self.client = client

    def extract(
        self,
        repo: InMemoryRepository,
        profile: SceneProfile,
        topic_blocks: list[TopicBlock],
    ) -> list[CandidateObject]:
        candidates: list[CandidateObject] = []
        use_rule_fallback = False
        for topic_block in topic_blocks:
            if use_rule_fallback:
                candidates.extend(rule_candidates_for_topic_block(repo, profile, topic_block))
                continue
            system_prompt = build_extract_system_prompt(profile)
            user_prompt = build_extract_user_prompt(repo, topic_block)
            try:
                response = self.client.chat_json(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=0.0,
                )
            except Exception:
                use_rule_fallback = True
                candidates.extend(rule_candidates_for_topic_block(repo, profile, topic_block))
                continue
            for item in response.get("items", []):
                object_type = ObjectType(item["type"])
                if object_type not in profile.enabled_objects:
                    continue
                evidence_ids = []
                for segment_id in item.get("evidence_segment_ids", []):
                    if segment_id not in repo.segments:
                        continue
                    segment = repo.segments[segment_id]
                    evidence = repo.add_evidence(
                        record_id=segment.record_id,
                        segment_id=segment.id,
                        quote=segment.text,
                    )
                    evidence_ids.append(evidence.id)
                if not evidence_ids and topic_block.segment_ids:
                    segment = repo.segments[topic_block.segment_ids[0]]
                    evidence = repo.add_evidence(
                        record_id=segment.record_id,
                        segment_id=segment.id,
                        quote=segment.text,
                    )
                    evidence_ids.append(evidence.id)

                payload = item.get("payload", {})
                if not payload:
                    payload = fallback_payload(object_type, repo, topic_block)
                candidates.append(
                    CandidateObject(
                        id=repo.next_id("cand"),
                        type=object_type,
                        title=item["title"],
                        summary=item.get("summary") or item["title"],
                        payload=payload,
                        evidence_ids=evidence_ids,
                        topic_block_id=topic_block.id,
                        confidence=float(item.get("confidence", 0.75)),
                    )
                )
        return candidates


def rule_candidates_for_topic_block(
    repo: InMemoryRepository,
    profile: SceneProfile,
    topic_block: TopicBlock,
) -> list[CandidateObject]:
    candidates: list[CandidateObject] = []
    segment_text = " ".join(repo.segments[segment_id].text for segment_id in topic_block.segment_ids)
    for object_type, title, payload in infer_objects(segment_text):
        if object_type not in profile.enabled_objects:
            continue
        evidence_ids = []
        for segment_id in topic_block.segment_ids:
            segment = repo.segments[segment_id]
            evidence = repo.add_evidence(
                record_id=segment.record_id,
                segment_id=segment.id,
                quote=segment.text,
            )
            evidence_ids.append(evidence.id)
        candidates.append(
            CandidateObject(
                id=repo.next_id("cand"),
                type=object_type,
                title=title,
                summary=segment_text,
                payload=payload,
                evidence_ids=evidence_ids,
                topic_block_id=topic_block.id,
                confidence=0.68,
            )
        )
    return candidates


class LLMDigestRenderer:
    def __init__(self, client: JSONChatClient) -> None:
        self.client = client

    def render(
        self,
        record_id: str,
        workspace_id: str,
        scene: str,
        source_text: str,
        topic_blocks: list[TopicBlock],
        candidates: list[CandidateObject],
        changes: list[ChangeEvent],
    ) -> RecordDigest:
        try:
            return self.render_llm_top_down(
                record_id=record_id,
                workspace_id=workspace_id,
                scene=scene,
                source_text=source_text,
                topic_blocks=topic_blocks,
                candidates=candidates,
                changes=changes,
            )
        except Exception as exc:
            base_digest = render_top_down_digest(
                record_id=record_id,
                workspace_id=workspace_id,
                scene=scene,
                source_text=source_text,
                topic_blocks=topic_blocks,
                candidates=candidates,
                changes=changes,
            )
            base_digest.plan["llm_digest"] = {"status": "fallback", "error": str(exc)}
            return base_digest

    def render_llm_top_down(
        self,
        *,
        record_id: str,
        workspace_id: str,
        scene: str,
        source_text: str,
        topic_blocks: list[TopicBlock],
        candidates: list[CandidateObject],
        changes: list[ChangeEvent],
    ) -> RecordDigest:
        source_stats = build_source_stats(topic_blocks, candidates, source_text)
        expected_levels = choose_digest_levels(source_stats)
        planner_response = self.client.chat_json(
            system_prompt=build_outline_system_prompt(scene, expected_levels),
            user_prompt=build_outline_user_prompt(
                scene=scene,
                source_text=source_text,
                source_stats=source_stats,
                expected_levels=expected_levels,
                topic_blocks=topic_blocks,
                candidates=candidates,
                changes=changes,
            ),
            temperature=0.0,
        )
        outline = normalize_outline_response(planner_response, expected_levels)
        validate_outline_coverage(outline, topic_blocks, expected_levels)

        sections = []
        topic_by_id = {block.id: block for block in topic_blocks}
        candidates_by_topic: dict[str, list[CandidateObject]] = {}
        for candidate in candidates:
            candidates_by_topic.setdefault(candidate.topic_block_id, []).append(candidate)

        for path, leaf in iter_leaf_outline_nodes(outline):
            leaf_topic_blocks = [
                topic_by_id[block_id]
                for block_id in leaf.get("topic_block_ids", [])
                if block_id in topic_by_id
            ]
            leaf_candidates = [
                candidate
                for block in leaf_topic_blocks
                for candidate in candidates_by_topic.get(block.id, [])
            ]
            section_response = self.client.chat_json(
                system_prompt=build_section_system_prompt(scene, leaf.get("level", "section")),
                user_prompt=build_section_user_prompt(
                    scene=scene,
                    source_text=source_text,
                    outline_path=path,
                    outline_node=leaf,
                    topic_blocks=leaf_topic_blocks,
                    candidates=leaf_candidates,
                    changes=changes,
                ),
                temperature=0.0,
            )
            sections.append(
                normalize_section_response(
                    section_response,
                    leaf=leaf,
                    outline_path=path,
                    topic_blocks=leaf_topic_blocks,
                    candidates=leaf_candidates,
                )
            )

        coverage = build_coverage_report(topic_blocks, sections)
        reconcile = reconcile_digest_sections(topic_blocks, sections, candidates)
        plan = {
            "engine": "llm_top_down_digest_v1",
            "strategy": "llm_outline_then_leaf_writes",
            "levels": expected_levels,
            "source_stats": source_stats,
            "outline": outline,
            "coverage": coverage,
            "reconcile": reconcile,
            "patch_contract": {
                "operations": ["replace_section", "insert_key_point", "split_section", "mark_uncertain"],
                "identity_field": "section_id",
                "evidence_rule": "patches may change wording but must keep or explicitly update evidence ids",
            },
            "object_counts": count_candidates_by_type(candidates),
            "llm_outline": {"status": "applied", "leaf_count": len(sections)},
        }
        return RecordDigest(
            record_id=record_id,
            workspace_id=workspace_id,
            scene=scene,
            one_line_summary=build_one_line_summary(topic_blocks, candidates, changes, expected_levels),
            topic_blocks=topic_blocks,
            extracted_objects=candidates,
            change_events=changes,
            plan=plan,
            sections=sections,
            evidence_index=build_digest_evidence_index(topic_blocks, candidates),
            processing_trace=[
                {
                    "skill": "record_digest_v1",
                    "version": "2.0",
                    "engine": "llm_top_down_digest_v1",
                    "input_topic_blocks": len(topic_blocks),
                    "output_sections": len(sections),
                    "outline_nodes": count_outline_nodes(outline),
                    "coverage_ratio": coverage["coverage_ratio"],
                }
            ],
        )


def build_outline_system_prompt(scene: str, expected_levels: list[str]) -> str:
    return (
        "你是 RecordFlow 的顶层大纲规划器。"
        "你必须先通读完整文本，再输出树状大纲。"
        "不要按句子或零散点位切碎内容。"
        f"当前层级要求是：{'/'.join(expected_levels)}。"
        "如果文本很长，要优先合并成更大的主题单元，而不是拆成很多小点。"
        "必须返回 JSON。"
        f"当前场景是：{scene}。"
    )


def build_outline_user_prompt(
    *,
    scene: str,
    source_text: str,
    source_stats: dict[str, int],
    expected_levels: list[str],
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
    changes: list[ChangeEvent],
) -> str:
    payload = {
        "scene": scene,
        "expected_levels": expected_levels,
        "source_stats": source_stats,
        "source_text": source_text,
        "topic_blocks": [
            {
                "id": block.id,
                "topic": block.topic,
                "summary": block.summary,
                "segment_ids": block.segment_ids,
                "importance": block.importance,
            }
            for block in topic_blocks
        ],
        "candidate_summary": [
            {
                "id": candidate.id,
                "type": candidate.type.value,
                "title": candidate.title,
                "topic_block_id": candidate.topic_block_id,
            }
            for candidate in candidates
        ],
        "changes": [
            {
                "id": change.id,
                "change_type": change.change_type.value,
                "summary": change.summary,
            }
            for change in changes
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def build_section_system_prompt(scene: str, level: str) -> str:
    return (
        "你是 RecordFlow 的章节写作器。"
        "你必须根据已规划的大纲节点，把该叶子节点写成完整、连贯、忠实的章节。"
        "不要把内容拆成很多很碎的小点。"
        f"当前写作层级是：{level}。"
        f"场景：{scene}。"
        "必须返回 JSON。"
    )


def build_section_user_prompt(
    *,
    scene: str,
    source_text: str,
    outline_path: list[str],
    outline_node: dict[str, Any],
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
    changes: list[ChangeEvent],
) -> str:
    payload = {
        "scene": scene,
        "outline_path": outline_path,
        "outline_node": outline_node,
        "source_text": source_text,
        "topic_blocks": [
            {
                "id": block.id,
                "topic": block.topic,
                "summary": block.summary,
                "segment_ids": block.segment_ids,
                "importance": block.importance,
            }
            for block in topic_blocks
        ],
        "candidates": [
            {
                "id": candidate.id,
                "type": candidate.type.value,
                "title": candidate.title,
                "summary": candidate.summary,
                "topic_block_id": candidate.topic_block_id,
            }
            for candidate in candidates
        ],
        "changes": [
            {
                "id": change.id,
                "change_type": change.change_type.value,
                "summary": change.summary,
            }
            for change in changes
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def normalize_outline_response(response: dict[str, Any], expected_levels: list[str]) -> list[dict[str, Any]]:
    outline = response.get("outline")
    if not isinstance(outline, list) or not outline:
        raise ValueError("LLM outline response must include a non-empty outline list.")
    levels = response.get("levels") or expected_levels
    if list(levels) != expected_levels:
        raise ValueError("LLM outline response levels do not match the expected length-based levels.")
    return outline


def normalize_section_response(
    response: dict[str, Any],
    *,
    leaf: dict[str, Any],
    outline_path: list[str],
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
) -> dict[str, Any]:
    segment_ids = unique_segment_ids(topic_blocks)
    section = {
        "id": response.get("id") or f"section_{leaf.get('id', 'leaf')}",
        "outline_node_id": leaf.get("id"),
        "outline_path": outline_path,
        "title": response.get("title") or leaf.get("title") or "未命名章节",
        "purpose": response.get("purpose") or leaf.get("purpose") or "",
        "summary": response.get("summary") or summarize_topic_group(topic_blocks),
        "detailed_summary": response.get("detailed_summary") or build_detailed_summary(topic_blocks, candidates),
        "key_points": response.get("key_points") or build_key_points(topic_blocks, candidates),
        "decisions": response.get("decisions") or [candidate.title for candidate in candidates if candidate.type == ObjectType.DECISION],
        "tasks": response.get("tasks") or [candidate.title for candidate in candidates if candidate.type == ObjectType.TASK],
        "questions": response.get("questions") or [candidate.title for candidate in candidates if candidate.type == ObjectType.QUESTION],
        "risks": response.get("risks") or [candidate.title for candidate in candidates if candidate.type == ObjectType.RISK],
        "object_counts": response.get("object_counts") or count_candidates_by_type(candidates),
        "evidence_span": {
            "topic_block_ids": [block.id for block in topic_blocks],
            "segment_ids": segment_ids,
        },
        "evidence_segment_ids": response.get("evidence_segment_ids") or segment_ids,
        "topic_block_ids": [block.id for block in topic_blocks],
    }
    if "uncertainty" in response:
        section["uncertainty"] = response["uncertainty"]
    return section


def validate_outline_coverage(
    outline: list[dict[str, Any]],
    topic_blocks: list[TopicBlock],
    expected_levels: list[str],
) -> None:
    seen_ids: list[str] = []
    leaf_count = 0
    for _path, leaf in iter_leaf_outline_nodes(outline):
        leaf_count += 1
        seen_ids.extend(leaf.get("topic_block_ids", []))
    expected_ids = [block.id for block in topic_blocks]
    if sorted(seen_ids) != sorted(expected_ids):
        raise ValueError("LLM outline must cover every topic block exactly once.")
    outline_levels = collect_outline_levels(outline)
    if outline_levels != expected_levels:
        raise ValueError("LLM outline levels do not match the requested hierarchy.")
    if leaf_count == 0:
        raise ValueError("LLM outline must contain at least one leaf node.")


def collect_outline_levels(outline: list[dict[str, Any]]) -> list[str]:
    levels: list[str] = []
    node = outline
    while node:
        level = node[0].get("level")
        if level:
            levels.append(level)
        child = node[0].get("children") or []
        node = child
    return levels


def build_extract_system_prompt(profile: SceneProfile) -> str:
    allowed_types = ", ".join(object_type.value for object_type in profile.enabled_objects)
    return (
        "你是 RecordFlow 的结构化抽取器。"
        "只从用户提供的转写片段中抽取明确存在的信息，不要编造。"
        f"允许的对象类型只有：{allowed_types}。"
        "必须返回 JSON，不要返回 Markdown。"
        "格式：{\"items\":[{\"type\":\"Task\",\"title\":\"...\",\"summary\":\"...\","
        "\"payload\":{},\"evidence_segment_ids\":[\"seg_001\"],\"confidence\":0.8}]}"
    )


def build_extract_user_prompt(repo: InMemoryRepository, topic_block: TopicBlock) -> str:
    segments = [
        {
            "id": segment_id,
            "text": repo.segments[segment_id].text,
        }
        for segment_id in topic_block.segment_ids
    ]
    payload = {
        "topic": topic_block.topic,
        "summary": topic_block.summary,
        "segments": segments,
    }
    return json.dumps(payload, ensure_ascii=False)


def fallback_payload(
    object_type: ObjectType,
    repo: InMemoryRepository,
    topic_block: TopicBlock,
) -> dict:
    text = "。".join(repo.segments[segment_id].text for segment_id in topic_block.segment_ids)
    for inferred_type, _title, payload in infer_objects(text):
        if inferred_type == object_type:
            return payload
    return {}
