from __future__ import annotations

import argparse
from pathlib import Path
from urllib.request import urlopen


DEFAULT_INDEX_URL = "https://platform.stepfun.com/docs/llms.txt"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "stepfun_docs_index.txt"


def fetch_text(url: str, timeout: int) -> str:
    with urlopen(url, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch StepFun documentation index and write it to a local text file."
    )
    parser.add_argument("--url", default=DEFAULT_INDEX_URL)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    content = fetch_text(args.url, args.timeout)
    output_path = Path(args.output)
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote {len(content)} chars to {output_path}")


if __name__ == "__main__":
    main()
