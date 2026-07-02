import argparse
import time

from recordflow_agent.repository_factory import create_repository


def enqueue_cleanup_job(repo: object) -> str:
    if not hasattr(repo, "enqueue_cleanup_job"):
        raise RuntimeError("The current repository does not support enqueue_cleanup_job().")
    return repo.enqueue_cleanup_job()


def run_scheduler(repo: object, *, once: bool, interval_seconds: float) -> None:
    while True:
        enqueue_cleanup_job(repo)
        if once:
            return
        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue periodic cleanup jobs for the ASR website.")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=3600.0)
    args = parser.parse_args()
    repo = create_repository()
    try:
        run_scheduler(repo, once=args.once, interval_seconds=args.interval_seconds)
    finally:
        if hasattr(repo, "close"):
            repo.close()


if __name__ == "__main__":
    main()
