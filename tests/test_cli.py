from pathlib import Path

from recordflow_agent.cli import run_files


def test_run_files_processes_multiple_records_in_one_workspace(tmp_path: Path):
    first = tmp_path / "record_1.txt"
    second = tmp_path / "record_2.txt"
    first.write_text("张三负责后端，周五前完成。", encoding="utf-8")
    second.write_text("后端截止时间不用周五了，提前到周三下班前完成。", encoding="utf-8")

    output = run_files(
        input_paths=[first, second],
        profile_name="project_meeting",
        workspace_name="RecordFlow product",
    )

    tasks = [
        obj for obj in output["state_objects"] if obj["type"] == "Task"
    ]

    assert len(output["digests"]) == 2
    assert len(tasks) == 1
    assert tasks[0]["payload"]["due_date"] == "周三下班前"
