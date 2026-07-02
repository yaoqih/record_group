from __future__ import annotations

import re
from typing import Any

from recordflow_agent.profiles import SceneProfile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.schemas import (
    CandidateObject,
    ChangeEvent,
    ChangeType,
    ObjectType,
    RecordDigest,
    StateObject,
    TopicBlock,
    TranscriptSegment,
)


SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s+|[。！？!?]\s*|(?<=[.])\s+")
MAX_SEGMENTS_PER_RECORD = 80
MAX_SEGMENT_CHARS = 320
OBJECT_LABELS: dict[str, ObjectType] = {
    "事实": ObjectType.FACT,
    "决定": ObjectType.DECISION,
    "决策": ObjectType.DECISION,
    "任务": ObjectType.TASK,
    "待办": ObjectType.TASK,
    "问题": ObjectType.QUESTION,
    "风险": ObjectType.RISK,
    "需求": ObjectType.REQUIREMENT,
    "异议": ObjectType.OBJECTION,
    "反对": ObjectType.OBJECTION,
    "想法": ObjectType.IDEA,
    "洞察": ObjectType.INSIGHT,
    "知识点": ObjectType.KNOWLEDGE,
    "知识": ObjectType.KNOWLEDGE,
    "原话": ObjectType.QUOTE,
    "引用": ObjectType.QUOTE,
    "时间线": ObjectType.TIMELINE_EVENT,
    "事件": ObjectType.TIMELINE_EVENT,
    "实体": ObjectType.ENTITY,
}
OBJECT_TOPIC_NAMES: dict[ObjectType, str] = {
    ObjectType.FACT: "事实",
    ObjectType.DECISION: "决策",
    ObjectType.TASK: "任务推进",
    ObjectType.QUESTION: "未解问题",
    ObjectType.RISK: "风险",
    ObjectType.REQUIREMENT: "需求",
    ObjectType.OBJECTION: "异议",
    ObjectType.IDEA: "想法",
    ObjectType.INSIGHT: "洞察",
    ObjectType.KNOWLEDGE: "知识",
    ObjectType.QUOTE: "原话",
    ObjectType.TIMELINE_EVENT: "时间线",
    ObjectType.ENTITY: "实体",
}


def normalize_sentences(text: str) -> list[str]:
    sentences = [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    return sentences or [text.strip()]


def normalize_segments(text: str, max_segments: int = MAX_SEGMENTS_PER_RECORD) -> list[str]:
    sentences = normalize_sentences(text)
    if len(sentences) <= max_segments:
        return sentences
    group_size = max(1, -(-len(sentences) // max_segments))
    return [
        " ".join(sentences[start : start + group_size])
        for start in range(0, len(sentences), group_size)
    ]


def segment_topics(
    repo: InMemoryRepository,
    record_id: str,
    segments: list[TranscriptSegment],
) -> list[TopicBlock]:
    topic_blocks: list[TopicBlock] = []
    for segment in segments:
        topic = infer_topic(segment.text)
        topic_block = TopicBlock(
            id=repo.next_id("topic"),
            record_id=record_id,
            topic=topic,
            summary=segment.text,
            segment_ids=[segment.id],
            importance="high" if topic in {"任务推进", "决策", "风险"} else "medium",
        )
        topic_blocks.append(repo.add_topic_block(topic_block))
    return topic_blocks


def infer_topic(text: str) -> str:
    labeled = match_labeled_object(text)
    if labeled is not None:
        object_type, _content, _status_hint = labeled
        return OBJECT_TOPIC_NAMES[object_type]
    lowered = text.lower()
    if contains_any(text, ("决定", "确定", "先做", "改成")) or contains_any(
        lowered,
        ("decided", "decision", "make a decision", "we will", "we chose"),
    ):
        return "决策"
    if contains_any(text, ("负责", "完成", "截止", "交付", "新增")) or contains_any(
        lowered,
        ("responsible for", "by friday", "by monday", "by tomorrow", "complete", "deliver"),
    ):
        return "任务推进"
    if contains_any(text, ("风险", "担心", "拖慢", "阻塞", "不稳定")) or contains_any(
        lowered,
        ("risk", "concern", "blocked", "unstable", "increase cost"),
    ):
        return "风险"
    if contains_any(text, ("需要", "希望", "必须", "客户")) or contains_any(
        lowered,
        (
            "need to",
            "needs to",
            "require",
            "must",
            "customer",
            "would like",
            "i'd like",
            "i want to",
            "i need",
            "can i",
            "could you",
        ),
    ):
        return "需求"
    return "讨论要点"


def extract_objects(
    repo: InMemoryRepository,
    profile: SceneProfile,
    topic_blocks: list[TopicBlock],
) -> list[CandidateObject]:
    extracted: list[CandidateObject] = []
    for topic_block in topic_blocks:
        segment_text = " ".join(repo.segments[segment_id].text for segment_id in topic_block.segment_ids)
        for object_type, title, payload in infer_objects(segment_text):
            if object_type not in profile.enabled_objects:
                continue
            evidence_ids = []
            for block_segment_id in topic_block.segment_ids:
                block_segment = repo.segments[block_segment_id]
                evidence = repo.add_evidence(
                    record_id=block_segment.record_id,
                    segment_id=block_segment.id,
                    quote=block_segment.text,
                )
                evidence_ids.append(evidence.id)
            extracted.append(
                CandidateObject(
                    id=repo.next_id("cand"),
                    type=object_type,
                    title=title,
                    summary=segment_text,
                    payload=payload,
                    evidence_ids=evidence_ids,
                    topic_block_id=topic_block.id,
                    confidence=0.82,
                )
            )
    return extracted


def infer_objects(text: str) -> list[tuple[ObjectType, str, dict[str, str | None]]]:
    labeled = match_labeled_object(text)
    if labeled is not None:
        object_type, content, status_hint = labeled
        return [build_labeled_object(object_type, content, status_hint)]

    objects: list[tuple[ObjectType, str, dict[str, Any]]] = []
    lowered = text.lower()

    if contains_any(text, ("决定", "确定", "先做", "改成")) or contains_any(
        lowered,
        ("decided", "decision", "make a decision", "we will", "we chose"),
    ):
        decision = clean_marker(text, ("决定", "确定"))
        objects.append(
            (
                ObjectType.DECISION,
                shorten_title(decision),
                {
                    "decision": decision,
                    "reason": None,
                    "merge_key": build_merge_key(ObjectType.DECISION, decision),
                },
            )
        )

    task_payload = infer_task_payload(text)
    if task_payload:
        objects.append(
            (
                ObjectType.TASK,
                task_payload["title"],
                {
                    "owner": task_payload.get("owner"),
                    "action": task_payload["action"],
                    "due_date": task_payload.get("due_date"),
                    "merge_key": task_payload["merge_key"],
                },
            )
        )

    if contains_any(text, ("风险", "担心", "拖慢", "阻塞", "不稳定")) or contains_any(
        lowered,
        ("risk", "concern", "blocked", "unstable", "increase cost"),
    ):
        objects.append(
            (
                ObjectType.RISK,
                shorten_title(text),
                {
                    "risk_event": text,
                    "impact": "medium",
                    "merge_key": build_merge_key(ObjectType.RISK, text),
                },
            )
        )

    if contains_any(text, ("需要", "希望", "必须支持", "客户")) or contains_any(
        lowered,
        (
            "need to",
            "needs to",
            "require",
            "must",
            "customer",
            "would like",
            "i'd like",
            "i want to",
            "i need",
            "can i",
            "could you",
        ),
    ):
        objects.append(
            (
                ObjectType.REQUIREMENT,
                shorten_title(text),
                {
                    "need": text,
                    "requester": "unknown",
                    "merge_key": build_merge_key(ObjectType.REQUIREMENT, text),
                },
            )
        )

    if "？" in text or "?" in text or contains_any(text, ("不确定", "待确认", "需要确认")):
        objects.append(
            (
                ObjectType.QUESTION,
                shorten_title(text),
                {
                    "question": text,
                    "answer_status": "open",
                    "merge_key": build_merge_key(ObjectType.QUESTION, text),
                },
            )
        )

    return objects


def match_labeled_object(text: str) -> tuple[ObjectType, str, str | None] | None:
    cleaned = text.strip()
    match = re.match(
        r"^(?P<label>[\u4e00-\u9fa5A-Za-z]+?)(?P<status>已解决|完成|已完成|关闭)?\s*[：:]\s*(?P<content>.+)$",
        cleaned,
    )
    if not match:
        return None
    label = match.group("label")
    object_type = OBJECT_LABELS.get(label)
    if object_type is None:
        return None
    return object_type, match.group("content").strip("，。；; "), match.group("status")


def build_labeled_object(
    object_type: ObjectType,
    content: str,
    status_hint: str | None,
) -> tuple[ObjectType, str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "merge_key": build_merge_key(object_type, content),
    }
    title = shorten_title(content)

    if object_type == ObjectType.FACT:
        payload.update({"subject": infer_subject(content), "predicate": "state", "value": content, "scope": None})
    elif object_type == ObjectType.DECISION:
        payload.update({"decision": content, "reason": None, "participants": [], "reversible": None})
    elif object_type == ObjectType.TASK:
        task_payload = infer_task_payload(content) or {
            "title": title,
            "owner": infer_owner(content),
            "action": normalize_task_action(content),
            "due_date": infer_due_date(content),
            "merge_key": build_merge_key(ObjectType.TASK, normalize_task_action(content)),
        }
        payload.update(task_payload)
        title = str(task_payload["title"])
    elif object_type == ObjectType.QUESTION:
        payload.update({"question": content, "owner": infer_owner(content), "answer_status": "open", "blocking_level": None})
    elif object_type == ObjectType.RISK:
        payload.update({"risk_event": normalize_closed_prefix(content), "impact": "medium", "probability": None, "mitigation": None, "owner": infer_owner(content)})
    elif object_type == ObjectType.REQUIREMENT:
        payload.update({"requester": infer_requester(content), "need": content, "scenario": None, "priority": None, "acceptance_hint": None})
    elif object_type == ObjectType.OBJECTION:
        payload.update({"objector": infer_requester(content), "objection": content, "reason": None, "severity": "medium", "response_history": []})
    elif object_type == ObjectType.IDEA:
        payload.update({"idea": content, "motivation": None, "related_topics": [], "maturity": "rough"})
    elif object_type == ObjectType.INSIGHT:
        payload.update({"insight": content, "supporting_objects": [], "scope": None, "confidence": "tentative"})
    elif object_type == ObjectType.KNOWLEDGE:
        payload.update({"concept": infer_concept(content), "definition": content, "steps": [], "examples": []})
    elif object_type == ObjectType.QUOTE:
        payload.update({"speaker": infer_speaker(content), "quote_text": clean_quote(content), "start_time": None, "end_time": None, "tags": []})
        title = shorten_title(payload["quote_text"])
    elif object_type == ObjectType.TIMELINE_EVENT:
        payload.update({"event": strip_time_prefix(content), "time": infer_time_expression(content), "actor": infer_owner(content), "related_objects": []})
    elif object_type == ObjectType.ENTITY:
        entity_name = infer_entity_name(content)
        payload.update({"name": entity_name, "entity_type": infer_entity_type(content), "aliases": [], "attributes": {"description": content}, "relations": []})
        title = entity_name

    if status_hint:
        payload["status_hint"] = "closed"
    return object_type, title, payload


def infer_task_payload(text: str) -> dict[str, str | None] | None:
    lowered = text.lower()
    if not (
        contains_any(text, ("负责", "完成", "截止", "交付", "新增"))
        or contains_any(
            lowered,
            ("responsible for", "by friday", "by monday", "by tomorrow", "complete", "deliver"),
        )
    ):
        return None

    owner = infer_owner(text)
    due_date = infer_due_date(text)
    action = normalize_task_action(text)
    return {
        "title": shorten_title(action),
        "owner": owner,
        "action": action,
        "due_date": due_date,
        "merge_key": build_merge_key(ObjectType.TASK, action),
    }


def normalize_task_action(text: str) -> str:
    normalized = text
    normalized = re.sub(r"^新增", "", normalized)
    normalized = re.sub(r"^[\u4e00-\u9fa5A-Za-z0-9_]{2,8}", "", normalized) if "提供" in normalized else normalized
    normalized = re.sub(r"周[一二三四五六日天][^，。；;]*?前", "", normalized)
    normalized = re.sub(r"不用[^，。；;]*了，?", "", normalized)
    normalized = re.sub(r"提前到[^，。；;]*", "", normalized)
    normalized = re.sub(r"截止时间", "", normalized)
    normalized = normalized.strip("，。；; 前")
    if "后端" in text:
        return "后端"
    if "Review Queue" in text:
        return "Review Queue"
    return normalized or text


def infer_owner(text: str) -> str | None:
    owner_match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9_]{2,8})(?:负责|周[一二三四五六日天]|今天|明天)", text)
    if owner_match:
        return owner_match.group(1)
    english_owner_match = re.search(
        r"\b([A-Z][A-Za-z0-9_]{1,30})\s+is\s+responsible\s+for\b",
        text,
    )
    if english_owner_match:
        return english_owner_match.group(1)
    return None


def infer_due_date(text: str) -> str | None:
    due_patterns = (
        r"(周[一二三四五六日天][^，。；;]*?前)",
        r"(周[一二三四五六日天]下班前)",
        r"(今天[^，。；;]*?前)",
        r"(明天[^，。；;]*?前)",
    )
    for pattern in due_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    english_due_match = re.search(r"\bby\s+([A-Za-z]+)\b", text, flags=re.IGNORECASE)
    if english_due_match:
        return f"by {english_due_match.group(1)}"
    return None


def infer_subject(text: str) -> str:
    for marker in ("目前", "已经", "是", "为"):
        if marker in text:
            return text.split(marker, 1)[0].strip("，。；; ") or shorten_title(text)
    return shorten_title(text)


def infer_requester(text: str) -> str:
    if "客户" in text:
        return "客户"
    return "unknown"


def infer_concept(text: str) -> str:
    match = re.match(r"([^，。；;需要是]+)", text)
    return match.group(1) if match else shorten_title(text)


def infer_speaker(text: str) -> str | None:
    match = re.match(r"([\u4e00-\u9fa5A-Za-z0-9_]{2,8})[说表示认为]+[：:]", text)
    return match.group(1) if match else None


def clean_quote(text: str) -> str:
    cleaned = re.sub(r"^[\u4e00-\u9fa5A-Za-z0-9_]{2,8}[说表示认为]+[：:]", "", text)
    return cleaned.strip("「」“”\"'，。；; ")


def infer_time_expression(text: str) -> str | None:
    match = re.search(r"(\d{1,2}\s*月\s*\d{1,2}\s*日|周[一二三四五六日天]|今天|明天|下周)", text)
    return match.group(1).replace(" ", "") if match else None


def strip_time_prefix(text: str) -> str:
    time_expr = infer_time_expression(text)
    if not time_expr:
        return text
    return text.replace(time_expr, "", 1).strip("，。；; ")


def infer_entity_name(text: str) -> str:
    match = re.search(r"(RecordFlow|[A-Z][A-Za-z0-9_-]*公司|[\u4e00-\u9fa5A-Za-z0-9_]{2,12})", text)
    return match.group(1) if match else shorten_title(text)


def infer_entity_type(text: str) -> str:
    if "公司" in text:
        return "organization"
    if contains_any(text, ("产品", "系统", "RecordFlow")):
        return "product"
    if contains_any(text, ("李工", "王工", "张三")):
        return "person"
    return "unknown"


def normalize_closed_prefix(text: str) -> str:
    return re.sub(r"^(已解决|完成|已完成|关闭)[：:，, ]*", "", text).strip()


def build_merge_key(object_type: ObjectType, text: str) -> str:
    normalized = normalize_key(normalize_closed_prefix(text))
    return f"{object_type.value}:{normalized[:80]}"


def merge_changes(
    repo: InMemoryRepository,
    workspace_id: str,
    record_id: str,
    candidates: list[CandidateObject],
) -> list[ChangeEvent]:
    changes: list[ChangeEvent] = []
    for candidate in candidates:
        existing = find_matching_state_object(
            candidate,
            repo.list_state_objects(workspace_id),
        )
        if existing is None:
            status = str(candidate.payload.get("status_hint") or "open")
            state_object = StateObject(
                id=repo.next_id("obj"),
                workspace_id=workspace_id,
                type=candidate.type,
                title=candidate.title,
                summary=candidate.summary,
                status=status,
                payload=dict(candidate.payload),
                evidence_ids=list(candidate.evidence_ids),
                confidence=candidate.confidence,
            )
            repo.add_state_object(state_object)
            change = ChangeEvent(
                id=repo.next_id("chg"),
                workspace_id=workspace_id,
                record_id=record_id,
                change_type=ChangeType.CREATE,
                target_object_id=state_object.id,
                candidate_object_id=candidate.id,
                summary=f"新增 {candidate.type.value}: {candidate.title}",
                requires_review=candidate.type in {ObjectType.DECISION, ObjectType.RISK},
                evidence_ids=candidate.evidence_ids,
            )
            changes.append(repo.add_change_event(change))
            continue

        field_changes = update_existing_object(existing, candidate)
        change_type = infer_change_type(existing, candidate, field_changes)
        repo.update_state_object(existing)
        change = ChangeEvent(
            id=repo.next_id("chg"),
            workspace_id=workspace_id,
            record_id=record_id,
            change_type=change_type,
            target_object_id=existing.id,
            candidate_object_id=candidate.id,
            summary=build_change_summary(existing, change_type),
            requires_review=bool(field_changes),
            evidence_ids=candidate.evidence_ids,
            field_changes=field_changes,
        )
        changes.append(repo.add_change_event(change))
    return changes


def infer_change_type(
    existing: StateObject,
    candidate: CandidateObject,
    field_changes: dict[str, dict[str, Any]],
) -> ChangeType:
    if candidate.payload.get("status_hint") == "closed" and existing.status == "closed":
        return ChangeType.CLOSE
    if field_changes:
        return ChangeType.UPDATE
    return ChangeType.DUPLICATE


def build_change_summary(existing: StateObject, change_type: ChangeType) -> str:
    if change_type == ChangeType.CLOSE:
        return f"关闭 {existing.type.value}: {existing.title}"
    if change_type == ChangeType.UPDATE:
        return f"更新 {existing.type.value}: {existing.title}"
    return f"重复表达 {existing.type.value}: {existing.title}"


def find_matching_state_object(
    candidate: CandidateObject,
    existing_objects: list[StateObject],
) -> StateObject | None:
    candidate_merge_key = normalize_key(str(candidate.payload.get("merge_key") or ""))
    for existing in existing_objects:
        if existing.type != candidate.type:
            continue
        existing_merge_key = normalize_key(str(existing.payload.get("merge_key") or ""))
        if candidate_merge_key and candidate_merge_key == existing_merge_key:
            return existing
        if existing.type == ObjectType.TASK and same_task(existing, candidate):
            return existing
        if normalize_key(existing.title) == normalize_key(candidate.title):
            return existing
    return None


def same_task(existing: StateObject, candidate: CandidateObject) -> bool:
    old_action = str(existing.payload.get("action") or existing.title)
    new_action = str(candidate.payload.get("action") or candidate.title)
    if normalize_key(old_action) == normalize_key(new_action):
        return True
    return "后端" in old_action and "后端" in new_action


def update_existing_object(
    existing: StateObject,
    candidate: CandidateObject,
) -> dict[str, dict[str, Any]]:
    field_changes: dict[str, dict[str, Any]] = {}
    if candidate.payload.get("status_hint") == "closed" and existing.status != "closed":
        field_changes["status"] = {"from": existing.status, "to": "closed"}
        existing.status = "closed"
    for key, new_value in candidate.payload.items():
        old_value = existing.payload.get(key)
        if key == "status_hint":
            continue
        if new_value and new_value != old_value:
            existing.payload[key] = new_value
            field_changes[key] = {"from": old_value, "to": new_value}
    if candidate.title != existing.title:
        field_changes["title"] = {"from": existing.title, "to": candidate.title}
        existing.title = candidate.title
    existing.summary = candidate.summary
    existing.evidence_ids.extend(
        evidence_id
        for evidence_id in candidate.evidence_ids
        if evidence_id not in existing.evidence_ids
    )
    return field_changes


def render_digest(
    record_id: str,
    workspace_id: str,
    scene: str,
    topic_blocks: list[TopicBlock],
    candidates: list[CandidateObject],
    changes: list[ChangeEvent],
    source_text: str = "",
    digest_renderer: object | None = None,
) -> RecordDigest:
    from recordflow_agent.digest_engine import render_top_down_digest

    if digest_renderer is not None:
        return digest_renderer.render(
            record_id=record_id,
            workspace_id=workspace_id,
            scene=scene,
            source_text=source_text,
            topic_blocks=topic_blocks,
            candidates=candidates,
            changes=changes,
        )
    return render_top_down_digest(
        record_id=record_id,
        workspace_id=workspace_id,
        scene=scene,
        source_text=source_text,
        topic_blocks=topic_blocks,
        candidates=candidates,
        changes=changes,
    )


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def clean_marker(text: str, markers: tuple[str, ...]) -> str:
    cleaned = text
    for marker in markers:
        cleaned = cleaned.replace(marker, "")
    return cleaned.strip("：:，。；; ")


def shorten_title(text: str, limit: int = 24) -> str:
    compact = text.strip("：:，。；; ")
    return compact if len(compact) <= limit else f"{compact[:limit]}..."


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())
