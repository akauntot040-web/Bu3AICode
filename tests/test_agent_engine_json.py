"""AgentEngine.run_cycle_jsonの単体テスト。"""

from __future__ import annotations

import json
from pathlib import Path

from promptagent.agent.agent_engine import AgentEngine
from promptagent.config import AgentConfig


def _minimal_config() -> AgentConfig:
    return AgentConfig(
        auto_run_tests=False, auto_run_lint=False, auto_type_check=False, auto_git_diff=False
    )


def test_run_cycle_json_applies_file_patches(tmp_path: Path) -> None:
    engine = AgentEngine(tmp_path, _minimal_config())
    response = json.dumps(
        {
            "summary": "新規ファイルを作成しました",
            "files": [{"path": "app.py", "content": "print('hi')", "action": "create"}],
            "commands": [],
            "todos": [],
            "notes": [],
            "task_complete": True,
        }
    )
    result = engine.run_cycle_json(response)

    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "print('hi')"
    assert result.json_response is not None
    assert result.json_response.summary == "新規ファイルを作成しました"
    assert result.task_complete is True
    assert result.next_prompt_request is None


def test_run_cycle_json_task_incomplete_when_flagged_false(tmp_path: Path) -> None:
    engine = AgentEngine(tmp_path, _minimal_config())
    response = json.dumps(
        {
            "summary": "途中経過",
            "files": [{"path": "app.py", "content": "x = 1", "action": "create"}],
            "commands": [],
            "todos": ["残りの実装をお願いします"],
            "notes": [],
            "task_complete": False,
        }
    )
    result = engine.run_cycle_json(response)
    assert result.task_complete is False


def test_run_cycle_json_handles_conflict_with_three_way_merge(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    snapshots = {"app.py": "line1\nline2\nline3\n"}
    target.write_text("line1\nCHANGED_EXTERNALLY\nline3\n", encoding="utf-8")

    engine = AgentEngine(tmp_path, _minimal_config())
    response = json.dumps(
        {
            "summary": "line3を修正",
            "files": [{"path": "app.py", "content": "line1\nline2\nAI_CHANGED\n", "action": "update"}],
            "commands": [],
            "todos": [],
            "notes": [],
            "task_complete": True,
        }
    )
    result = engine.run_cycle_json(response, snapshots=snapshots)

    assert len(result.conflicts) == 1
    assert result.conflicts[0].auto_merged is True
    merged = target.read_text(encoding="utf-8")
    assert "CHANGED_EXTERNALLY" in merged
    assert "AI_CHANGED" in merged
