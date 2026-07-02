from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from recordflow_agent.pipeline import process_record
from recordflow_agent.profiles import load_profile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.serialization import to_jsonable


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def build_demo_cases() -> list[dict[str, Any]]:
    return [
        build_single_call_case(),
        build_batch_calls_case(),
    ]


def demo_cases_json() -> str:
    return json.dumps(build_demo_cases(), ensure_ascii=False)


def build_single_call_case() -> dict[str, Any]:
    transcript_path = "data/eval/media_samples/customer_followup/customer_followup_01_minds14_joint_account.txt"
    manifest_item = manifest_item_by_id("data/eval/media_samples/manifest.json", "customer_followup_01")
    text = read_text(transcript_path)
    records = [
        {
            "title": "customer_followup_01_minds14_joint_account",
            "text": text,
            "source": manifest_item["source"],
            "source_url": manifest_item["source_url"],
            "transcript_path": transcript_path,
            "raw_path": manifest_item["raw_path"],
            "compressed_path": manifest_item["compressed_path"],
            "duration_seconds": manifest_item["raw_media"]["duration_seconds"],
        }
    ]
    return {
        "name": "MInDS-14 客服：联名账户真实通话",
        "workspace": "真实客服跟进样本",
        "profile": "customer_followup",
        "records": records,
        "precomputedResult": precompute_result(
            workspace="真实客服跟进样本",
            profile_name="customer_followup",
            records=records,
            sources=[
                {
                    "source": manifest_item["source"],
                    "source_url": manifest_item["source_url"],
                    "license_note": manifest_item["license_note"],
                    "transcript_path": transcript_path,
                    "raw_path": manifest_item["raw_path"],
                    "compressed_path": manifest_item["compressed_path"],
                    "duration_seconds": manifest_item["raw_media"]["duration_seconds"],
                }
            ],
        ),
    }


def build_batch_calls_case() -> dict[str, Any]:
    transcript_path = "data/eval/media_samples_long/customer_followup_many/customer_followup_batch_42_calls.txt"
    manifest_item = manifest_item_by_id("data/eval/media_samples_long/manifest_long.json", "customer_followup_batch_42_calls")
    text = read_text(transcript_path)
    records = [
        {
            "title": "customer_followup_batch_42_calls",
            "text": text,
            "source": manifest_item["source"],
            "source_url": manifest_item["source_url"],
            "transcript_path": transcript_path,
            "raw_path": manifest_item["raw_path"],
            "compressed_path": manifest_item["compressed_path"],
            "duration_seconds": manifest_item["raw_media"]["duration_seconds"],
        }
    ]
    return {
        "name": "MInDS-14 客服：42 条真实通话批量",
        "workspace": "真实客服批量样本",
        "profile": "customer_followup",
        "records": records,
        "precomputedResult": precompute_result(
            workspace="真实客服批量样本",
            profile_name="customer_followup",
            records=records,
            sources=[
                {
                    "source": manifest_item["source"],
                    "source_url": manifest_item["source_url"],
                    "license_note": "由 42 条真实 MInDS-14 短通话串接，用于批量工程测试；不是自然长通话。",
                    "transcript_path": transcript_path,
                    "raw_path": manifest_item["raw_path"],
                    "compressed_path": manifest_item["compressed_path"],
                    "duration_seconds": manifest_item["raw_media"]["duration_seconds"],
                }
            ],
        ),
    }


def precompute_result(
    *,
    workspace: str,
    profile_name: str,
    records: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    repo = InMemoryRepository()
    profile = load_profile(profile_name)
    workspace_id = repo.create_workspace(workspace, profile.name)
    digest = None
    for record in records:
        digest = process_record(
            repo=repo,
            workspace_id=workspace_id,
            profile=profile,
            title=str(record["title"]),
            text=str(record["text"]),
        )
    if digest is None:
        raise ValueError("Demo case must include at least one record.")
    digest_json = to_jsonable(digest)
    digest_json["processing_trace"].append(
        {
            "kind": "real_sample_replay",
            "source_count": len(sources),
            "record_count": len(records),
            "note": "前端只回放这些已处理结果，不重新提交处理任务。",
        }
    )
    digest_json["source_index"] = sources
    state = {
        "state_objects": to_jsonable(repo.list_state_objects(workspace_id)),
        "change_events": to_jsonable(repo.list_change_events(workspace_id)),
    }
    review = {
        "review_items": [
            to_jsonable(change)
            for change in repo.list_change_events(workspace_id)
            if change.requires_review
        ]
    }
    return {
        "digest": digest_json,
        "state": state,
        "review": review,
        "sources": sources,
    }


def manifest_item_by_id(manifest_path: str, item_id: str) -> dict[str, Any]:
    manifest = read_json(manifest_path)
    for item in manifest["items"]:
        if item["id"] == item_id:
            return item
    raise KeyError(f"Missing item {item_id} in {manifest_path}")


def read_json(path: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / path).read_text(encoding="utf-8"))


def read_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8").strip()
