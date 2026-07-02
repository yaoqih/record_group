from __future__ import annotations

from dataclasses import replace
from typing import Any

from recordflow_agent.schemas import CandidateObject, ChangeEvent, ChangeType, ObjectType, RecordDigest, TopicBlock


PATCH_OPERATIONS = [
    "replace_section",
    "insert_key_point",
    "split_section",
    "mark_uncertain",
]


def render_top_down_digest(
    *,
    record_id: str,
    workspace_id: str,
    scene: str,
    source_text: str = "",
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
    changes: list[ChangeEvent],
) -> RecordDigest:
    source_stats = build_source_stats(topic_blocks, candidates, source_text)
    levels = choose_digest_levels(source_stats)
    outline = build_outline(topic_blocks, levels)
    sections = generate_sections_from_outline(outline, topic_blocks, candidates)
    coverage = build_coverage_report(topic_blocks, sections)
    reconcile = reconcile_digest_sections(topic_blocks, sections, candidates)
    plan = {
        "engine": "top_down_digest_v1",
        "strategy": "top_down_sections",
        "levels": levels,
        "source_stats": source_stats,
        "outline": outline,
        "coverage": coverage,
        "reconcile": reconcile,
        "patch_contract": {
            "operations": PATCH_OPERATIONS,
            "identity_field": "section_id",
            "evidence_rule": "patches may change wording but must keep or explicitly update evidence ids",
        },
        "object_counts": count_candidates_by_type(candidates),
    }
    one_line = build_one_line_summary(topic_blocks, candidates, changes, levels)
    return RecordDigest(
        record_id=record_id,
        workspace_id=workspace_id,
        scene=scene,
        one_line_summary=one_line,
        topic_blocks=topic_blocks,
        extracted_objects=candidates,
        change_events=changes,
        plan=plan,
        sections=sections,
        evidence_index=build_digest_evidence_index(topic_blocks, candidates),
        processing_trace=[
            {
                "skill": "record_digest_v1",
                "version": "1.0",
                "engine": "top_down_digest_v1",
                "input_topic_blocks": len(topic_blocks),
                "output_sections": len(sections),
                "outline_nodes": count_outline_nodes(outline),
                "coverage_ratio": coverage["coverage_ratio"],
            }
        ],
    )


def choose_digest_levels(source_stats: dict[str, int]) -> list[str]:
    character_count = source_stats["character_count"]
    if character_count > 4500:
        return ["part", "chapter", "section"]
    if character_count > 1200:
        return ["chapter", "section"]
    return ["section"]


def build_source_stats(
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
    source_text: str = "",
) -> dict[str, int]:
    character_count = len(source_text) if source_text else sum(len(block.summary) for block in topic_blocks)
    return {
        "segment_count": len({segment_id for block in topic_blocks for segment_id in block.segment_ids}),
        "topic_block_count": len(topic_blocks),
        "high_importance_blocks": sum(1 for block in topic_blocks if block.importance == "high"),
        "character_count": character_count,
        "candidate_count": len(candidates),
    }


def build_outline(topic_blocks: list[TopicBlock], levels: list[str]) -> list[dict[str, Any]]:
    groups = group_topic_blocks_for_digest(
        topic_blocks,
        max_group_size=12 if levels == ["section"] else 6,
    )
    leaf_nodes = [
        {
            "id": f"outline_section_{index:03d}",
            "level": "section",
            "title": infer_digest_section_title(group),
            "purpose": f"忠实整理原始录音中关于{infer_digest_section_title(group)}的具体讨论和证据。",
            "topic_block_ids": [block.id for block in group],
            "segment_ids": unique_segment_ids(group),
            "expected_detail": "high" if any(block.importance == "high" for block in group) else "medium",
            "children": [],
        }
        for index, group in enumerate(groups, start=1)
    ]
    if levels == ["section"]:
        return leaf_nodes

    chapter_nodes = wrap_outline_nodes(
        leaf_nodes,
        level="chapter",
        group_size=4,
        id_prefix="outline_chapter",
    )
    if levels == ["chapter", "section"]:
        return chapter_nodes
    return wrap_outline_nodes(
        chapter_nodes,
        level="part",
        group_size=3,
        id_prefix="outline_part",
    )


def wrap_outline_nodes(
    nodes: list[dict[str, Any]],
    *,
    level: str,
    group_size: int,
    id_prefix: str,
) -> list[dict[str, Any]]:
    wrapped = []
    for index, start in enumerate(range(0, len(nodes), group_size), start=1):
        children = nodes[start : start + group_size]
        child_titles = [child["title"] for child in children]
        title = " / ".join(dict.fromkeys(child_titles[:3]))
        wrapped.append(
            {
                "id": f"{id_prefix}_{index:03d}",
                "level": level,
                "title": title,
                "purpose": f"建立{title}的上层结构，控制长录音输出层级。",
                "topic_block_ids": flatten_values(children, "topic_block_ids"),
                "segment_ids": flatten_values(children, "segment_ids"),
                "expected_detail": "high" if any(child["expected_detail"] == "high" for child in children) else "medium",
                "children": children,
            }
        )
    return wrapped


def generate_sections_from_outline(
    outline: list[dict[str, Any]],
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
) -> list[dict[str, Any]]:
    topic_by_id = {block.id: block for block in topic_blocks}
    candidates_by_topic: dict[str, list[CandidateObject]] = {}
    for candidate in candidates:
        candidates_by_topic.setdefault(candidate.topic_block_id, []).append(candidate)

    sections = []
    for path, leaf in iter_leaf_outline_nodes(outline):
        blocks = [topic_by_id[block_id] for block_id in leaf["topic_block_ids"] if block_id in topic_by_id]
        section_candidates = [
            candidate
            for block in blocks
            for candidate in candidates_by_topic.get(block.id, [])
        ]
        segment_ids = unique_segment_ids(blocks)
        section_id = f"section_{len(sections) + 1:03d}"
        sections.append(
            {
                "id": section_id,
                "outline_node_id": leaf["id"],
                "outline_path": path,
                "title": leaf["title"],
                "purpose": leaf["purpose"],
                "summary": summarize_topic_group(blocks),
                "detailed_summary": build_detailed_summary(blocks, section_candidates),
                "key_points": build_key_points(blocks, section_candidates),
                "decisions": titles_for_type(section_candidates, ObjectType.DECISION),
                "tasks": titles_for_type(section_candidates, ObjectType.TASK),
                "questions": titles_for_type(section_candidates, ObjectType.QUESTION),
                "risks": titles_for_type(section_candidates, ObjectType.RISK),
                "object_counts": count_candidates_by_type(section_candidates),
                "evidence_span": {
                    "topic_block_ids": [block.id for block in blocks],
                    "segment_ids": segment_ids,
                },
                "evidence_segment_ids": segment_ids,
                "topic_block_ids": [block.id for block in blocks],
            }
        )
    return sections


def apply_digest_patch(digest: RecordDigest, patch: dict[str, Any]) -> RecordDigest:
    op = patch.get("op")
    if op not in PATCH_OPERATIONS:
        raise ValueError(f"Unsupported digest patch operation: {op}")
    section_id = patch.get("section_id")
    sections = []
    changed = False
    for section in digest.sections:
        if section.get("id") != section_id:
            sections.append(dict(section))
            continue
        changed = True
        sections.append(apply_section_patch(section, patch))
    if not changed:
        raise KeyError(f"Digest section not found: {section_id}")
    processing_trace = list(digest.processing_trace) + [
        {
            "kind": "digest_patch",
            "op": op,
            "section_id": section_id,
            "status": "applied",
        }
    ]
    return replace(digest, sections=sections, processing_trace=processing_trace)


def apply_digest_patch_json(digest_json: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    digest = record_digest_from_json(digest_json)
    patched = apply_digest_patch(digest, patch)
    from recordflow_agent.serialization import to_jsonable

    return to_jsonable(patched)


def record_digest_from_json(data: dict[str, Any]) -> RecordDigest:
    return RecordDigest(
        record_id=data["record_id"],
        workspace_id=data["workspace_id"],
        scene=data["scene"],
        one_line_summary=data.get("one_line_summary", ""),
        topic_blocks=[
            TopicBlock(
                id=item["id"],
                record_id=item["record_id"],
                topic=item["topic"],
                summary=item["summary"],
                segment_ids=list(item.get("segment_ids", [])),
                importance=item.get("importance", "medium"),
            )
            for item in data.get("topic_blocks", [])
        ],
        extracted_objects=[
            CandidateObject(
                id=item["id"],
                type=ObjectType(item["type"]),
                title=item["title"],
                summary=item["summary"],
                payload=dict(item.get("payload", {})),
                evidence_ids=list(item.get("evidence_ids", [])),
                topic_block_id=item["topic_block_id"],
                confidence=float(item.get("confidence", 0.8)),
            )
            for item in data.get("extracted_objects", [])
        ],
        change_events=[
            ChangeEvent(
                id=item["id"],
                workspace_id=item["workspace_id"],
                record_id=item["record_id"],
                change_type=ChangeType(item["change_type"]),
                summary=item["summary"],
                target_object_id=item.get("target_object_id"),
                candidate_object_id=item["candidate_object_id"],
                requires_review=bool(item.get("requires_review", False)),
                evidence_ids=list(item.get("evidence_ids", [])),
                field_changes=dict(item.get("field_changes", {})),
            )
            for item in data.get("change_events", [])
        ],
        plan=data.get("plan", {}),
        sections=list(data.get("sections", [])),
        evidence_index=list(data.get("evidence_index", [])),
        processing_trace=list(data.get("processing_trace", [])),
    )


def apply_section_patch(section: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    updated = dict(section)
    op = patch["op"]
    if op == "replace_section":
        if "summary" in patch:
            updated["summary"] = patch["summary"]
        if "detailed_summary" in patch:
            updated["detailed_summary"] = patch["detailed_summary"]
        if "key_points" in patch:
            updated["key_points"] = patch["key_points"]
    elif op == "insert_key_point":
        updated["key_points"] = list(updated.get("key_points", [])) + [patch["text"]]
    elif op == "split_section":
        updated["split_suggestion"] = {
            "reason": patch.get("reason", ""),
            "proposed_titles": patch.get("titles", []),
        }
    elif op == "mark_uncertain":
        updated["uncertainty"] = patch.get("reason", "user marked this section uncertain")
    updated.setdefault("patch_history", []).append(
        {
            "op": op,
            "summary": patch.get("summary"),
            "reason": patch.get("reason"),
        }
    )
    return updated


def build_coverage_report(topic_blocks: list[TopicBlock], sections: list[dict[str, Any]]) -> dict[str, Any]:
    all_segments = {segment_id for block in topic_blocks for segment_id in block.segment_ids}
    covered_segments = {
        segment_id
        for section in sections
        for segment_id in section.get("evidence_span", {}).get("segment_ids", [])
    }
    missing = sorted(all_segments - covered_segments)
    total = len(all_segments)
    covered = len(covered_segments)
    return {
        "covered_segment_count": covered,
        "total_segment_count": total,
        "coverage_ratio": 1.0 if total == 0 else round(covered / total, 4),
        "missing_segment_ids": missing,
    }


def reconcile_digest_sections(
    topic_blocks: list[TopicBlock],
    sections: list[dict[str, Any]],
    candidates: list[CandidateObject],
) -> dict[str, Any]:
    coverage = build_coverage_report(topic_blocks, sections)
    duplicate_section_ids = sorted(find_duplicate_section_ids(sections))
    evidenceless = [
        section["id"]
        for section in sections
        if not section.get("evidence_span", {}).get("segment_ids")
    ]
    status = "ok" if coverage["coverage_ratio"] == 1.0 and not duplicate_section_ids and not evidenceless else "needs_review"
    return {
        "status": status,
        "checks": {
            "coverage_complete": coverage["coverage_ratio"] == 1.0,
            "duplicate_sections": duplicate_section_ids,
            "evidence_bound": not evidenceless,
            "candidate_count": len(candidates),
        },
        "review_notes": build_reconcile_notes(coverage, duplicate_section_ids, evidenceless),
    }


def build_reconcile_notes(
    coverage: dict[str, Any],
    duplicate_section_ids: list[str],
    evidenceless: list[str],
) -> list[str]:
    notes = []
    if coverage["missing_segment_ids"]:
        notes.append("Some transcript segments are not covered by digest sections.")
    if duplicate_section_ids:
        notes.append("Some sections share the same id.")
    if evidenceless:
        notes.append("Some sections have no evidence segment ids.")
    return notes


def build_digest_evidence_index(
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
) -> list[dict[str, Any]]:
    topic_segment_ids = {
        segment_id
        for block in topic_blocks
        for segment_id in block.segment_ids
    }
    candidate_evidence_ids = {
        evidence_id
        for candidate in candidates
        for evidence_id in candidate.evidence_ids
    }
    return [
        {"kind": "segment", "id": segment_id}
        for segment_id in sorted(topic_segment_ids)
    ] + [
        {"kind": "evidence", "id": evidence_id}
        for evidence_id in sorted(candidate_evidence_ids)
    ]


def group_topic_blocks_for_digest(
    topic_blocks: list[TopicBlock],
    *,
    max_group_size: int,
) -> list[list[TopicBlock]]:
    if not topic_blocks:
        return []
    groups: list[list[TopicBlock]] = []
    current: list[TopicBlock] = []
    current_topic = ""
    for block in topic_blocks:
        if current and (block.topic != current_topic or len(current) >= max_group_size):
            groups.append(current)
            current = []
        current.append(block)
        current_topic = block.topic
    if current:
        groups.append(current)
    return groups


def iter_leaf_outline_nodes(
    outline: list[dict[str, Any]],
    parent_path: list[str] | None = None,
):
    for node in outline:
        path = [*(parent_path or []), node["title"]]
        if not node.get("children"):
            yield path, node
            continue
        yield from iter_leaf_outline_nodes(node["children"], path)


def build_one_line_summary(
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
    changes: list[ChangeEvent],
    levels: list[str],
) -> str:
    topics = "、".join(dict.fromkeys(block.topic for block in topic_blocks)) or "空记录"
    return (
        f"本次记录按{'/'.join(levels)}自顶向下整理，覆盖{len(topic_blocks)}个主题块，"
        f"涉及{topics}，产生 {len(candidates)} 个结构化对象和 {len(changes)} 个变化。"
    )


def build_detailed_summary(
    blocks: list[TopicBlock],
    candidates: list[CandidateObject],
) -> str:
    source = " ".join(block.summary for block in blocks[:4])
    object_text = "；".join(f"{candidate.type.value}: {candidate.title}" for candidate in candidates[:6])
    if object_text:
        return f"{source} 本节关联结构化对象：{object_text}"
    return source


def build_key_points(
    blocks: list[TopicBlock],
    candidates: list[CandidateObject],
) -> list[str]:
    points = [shorten_title(block.summary, limit=90) for block in blocks[:6]]
    for candidate in candidates[:4]:
        point = f"{candidate.type.value}: {candidate.title}"
        if point not in points:
            points.append(point)
    return points


def summarize_topic_group(topic_blocks: list[TopicBlock]) -> str:
    if not topic_blocks:
        return ""
    topic = infer_digest_section_title(topic_blocks)
    important = [block.summary for block in topic_blocks if block.importance == "high"]
    source = important or [block.summary for block in topic_blocks]
    details = " ".join(shorten_title(item, limit=90) for item in source[:3])
    return f"本章节围绕{topic}展开，关键信息包括：{details}"


def infer_digest_section_title(topic_blocks: list[TopicBlock]) -> str:
    topics = list(dict.fromkeys(block.topic for block in topic_blocks))
    if len(topics) == 1:
        return topics[0]
    return " / ".join(topics[:3])


def titles_for_type(candidates: list[CandidateObject], object_type: ObjectType) -> list[str]:
    return [candidate.title for candidate in candidates if candidate.type == object_type]


def count_candidates_by_type(candidates: list[CandidateObject]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.type.value] = counts.get(candidate.type.value, 0) + 1
    return counts


def count_outline_nodes(outline: list[dict[str, Any]]) -> int:
    return sum(1 + count_outline_nodes(node.get("children", [])) for node in outline)


def unique_segment_ids(blocks: list[TopicBlock]) -> list[str]:
    return list(
        dict.fromkeys(
            segment_id
            for block in blocks
            for segment_id in block.segment_ids
        )
    )


def flatten_values(nodes: list[dict[str, Any]], key: str) -> list[Any]:
    return list(dict.fromkeys(value for node in nodes for value in node.get(key, [])))


def find_duplicate_section_ids(sections: list[dict[str, Any]]) -> set[str]:
    seen = set()
    duplicates = set()
    for section in sections:
        section_id = section["id"]
        if section_id in seen:
            duplicates.add(section_id)
        seen.add(section_id)
    return duplicates


def shorten_title(text: str, limit: int = 24) -> str:
    compact = text.strip("：:，。；; ")
    return compact if len(compact) <= limit else f"{compact[:limit]}..."
