"""AgentEngineの競合検出に関する単体テスト。"""

from __future__ import annotations

from pathlib import Path

from promptagent.agent.agent_engine import AgentEngine
from promptagent.config import AgentConfig


def _minimal_config() -> AgentConfig:
    return AgentConfig(
        auto_run_tests=False, auto_run_lint=False, auto_type_check=False, auto_git_diff=False
    )


def test_conflict_detected_when_file_changed_externally(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")

    # AIへ提示した時点のスナップショット(=元の内容)
    snapshots = {"app.py": "line1\nline2\nline3\n"}

    # プロンプト提示後、AIの回答を待つ間に外部でline2が書き換えられたとする
    target.write_text("line1\nCHANGED_BY_HUMAN\nline3\n", encoding="utf-8")

    engine = AgentEngine(tmp_path, _minimal_config())
    # AIはline3を書き換える提案をしている(line2は変更していない=重複しない)
    response = "### `app.py`\n```python\nline1\nline2\nAI_CHANGED\n```\n"
    result = engine.run_cycle(response, snapshots=snapshots)

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.relative_path == "app.py"
    assert conflict.auto_merged is True  # 変更箇所が重複しないので自動マージに成功する

    merged_content = target.read_text(encoding="utf-8")
    assert "CHANGED_BY_HUMAN" in merged_content
    assert "AI_CHANGED" in merged_content
    assert result.next_prompt_request is None  # 自動マージ成功のため追加対応は不要


def test_conflict_with_overlapping_changes_inserts_markers(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    snapshots = {"app.py": "line1\nline2\nline3\n"}

    # 外部変更とAI提案の両方がline2を書き換える(重複=衝突)
    target.write_text("line1\nCHANGED_BY_HUMAN\nline3\n", encoding="utf-8")

    engine = AgentEngine(tmp_path, _minimal_config())
    response = "### `app.py`\n```python\nline1\nAI_CHANGED\nline3\n```\n"
    result = engine.run_cycle(response, snapshots=snapshots)

    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.auto_merged is False
    assert conflict.merge_conflict_markers >= 1

    merged_content = target.read_text(encoding="utf-8")
    assert "<<<<<<< THEIRS" in merged_content
    assert ">>>>>>> OURS" in merged_content
    assert result.next_prompt_request is not None  # 手動解決が必要なため次プロンプトを生成


def test_no_conflict_when_file_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("original_content\n", encoding="utf-8")
    snapshots = {"app.py": "original_content\n"}

    engine = AgentEngine(tmp_path, _minimal_config())
    response = "### `app.py`\n```python\nai_proposed_content\n```\n"
    result = engine.run_cycle(response, snapshots=snapshots)

    assert result.conflicts == []
    assert target.read_text(encoding="utf-8") == "ai_proposed_content"


def test_no_conflict_check_when_snapshot_missing(tmp_path: Path) -> None:
    target = tmp_path / "new_file.py"
    engine = AgentEngine(tmp_path, _minimal_config())
    response = "### `new_file.py`\n```python\nvalue = 1\n```\n"
    result = engine.run_cycle(response, snapshots={})

    assert result.conflicts == []
    assert target.exists()
