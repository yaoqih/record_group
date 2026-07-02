from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from recordflow_agent.pipeline import process_record
from recordflow_agent.llm_client import LLMConfig, OpenAICompatibleClient
from recordflow_agent.llm_skills import LLMDigestRenderer, LLMExtractor
from recordflow_agent.profiles import load_profile
from recordflow_agent.repository import InMemoryRepository
from recordflow_agent.schemas import RecordDigest
from recordflow_agent.serialization import to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RecordFlow MVP pipeline for transcription/proofreading or detailed summarization.")
    parser.add_argument("input", type=Path, nargs="+", help="Transcript text file(s).")
    parser.add_argument("--profile", default="detailed_summary")
    parser.add_argument("--workspace", default="RecordFlow MVP")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use RECORDFLOW_LLM_* environment variables for LLM extraction.",
    )
    args = parser.parse_args()

    output = run_files(
        input_paths=args.input,
        profile_name=args.profile,
        workspace_name=args.workspace,
        use_llm=args.use_llm,
    )
    print(json.dumps(output, ensure_ascii=False, indent=2 if args.pretty else None))


def run_files(
    input_paths: list[Path],
    profile_name: str,
    workspace_name: str,
    use_llm: bool = False,
) -> dict[str, Any]:
    profile = load_profile(profile_name)
    repo = InMemoryRepository()
    workspace_id = repo.create_workspace(workspace_name, profile.name)
    extractor = build_extractor(use_llm)
    digest_renderer = build_digest_renderer(use_llm)
    digests: list[RecordDigest] = []
    for input_path in input_paths:
        text = input_path.read_text(encoding="utf-8")
        digest = process_record(
            repo=repo,
            workspace_id=workspace_id,
            profile=profile,
            title=input_path.stem,
            text=text,
            extractor=extractor,
            digest_renderer=digest_renderer,
        )
        digests.append(digest)
    return {
        "digests": [serialize_digest(digest) for digest in digests],
        "state_objects": to_jsonable(repo.list_state_objects(workspace_id)),
        "change_events": to_jsonable(repo.list_change_events(workspace_id)),
    }


def build_extractor(use_llm: bool) -> LLMExtractor | None:
    if not use_llm:
        return None
    return LLMExtractor(OpenAICompatibleClient(LLMConfig.from_env()))


def build_digest_renderer(use_llm: bool) -> LLMDigestRenderer | None:
    if not use_llm:
        return None
    return LLMDigestRenderer(OpenAICompatibleClient(LLMConfig.from_env()))


def serialize_digest(digest: RecordDigest) -> dict[str, Any]:
    return to_jsonable(digest)


if __name__ == "__main__":
    main()
