"""AutonomousRunnerの単体テスト。実際のGemini API呼び出しはモックする。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from promptagent.ai_backend.gemini_client import GeminiResponse
from promptagent.autonomous.autonomous_runner import (
    AutonomousModeNotAvailableError,
    AutonomousRunner,
)
from promptagent.cli import PromptAgentApp


@pytest.fixture
def cli_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PromptAgentApp:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sample.py").write_text("print('hi')\n", encoding="utf-8")
    app = PromptAgentApp(tmp_path)
    app.bootstrap()
    yield app
    app.cache.close()


def _json_response(**overrides: object) -> str:
    payload = {
        "summary": "完了しました",
        "files": [],
        "commands": [],
        "todos": [],
        "notes": [],
        "task_complete": True,
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_raises_when_provider_is_not_google_ai_studio(cli_app: PromptAgentApp) -> None:
    cli_app.config.ai_backend.provider = "human"
    with pytest.raises(AutonomousModeNotAvailableError):
        AutonomousRunner(cli_app)


def test_stops_after_single_completed_iteration(cli_app: PromptAgentApp) -> None:
    cli_app.config.ai_backend.provider = "google_ai_studio"
    cli_app.config.ai_backend.api_key = "dummy-key"

    fake_client = MagicMock()
    fake_client.generate.return_value = GeminiResponse(
        text=_json_response(
            files=[{"path": "sample.py", "content": "print('done')", "action": "update"}]
        ),
        raw={},
    )

    runner = AutonomousRunner(cli_app, gemini_client=fake_client)
    summary = runner.run("sample.pyを完成させて", max_iterations=5)

    assert summary.completed is True
    assert summary.iteration_count == 1
    assert (cli_app.project_root / "sample.py").read_text(encoding="utf-8") == "print('done')"
    fake_client.generate.assert_called_once()


def test_continues_when_task_incomplete_and_stops_at_max_iterations(cli_app: PromptAgentApp) -> None:
    cli_app.config.ai_backend.provider = "google_ai_studio"
    cli_app.config.ai_backend.api_key = "dummy-key"
    cli_app.config.agent.auto_run_tests = False
    cli_app.config.agent.auto_run_lint = False
    cli_app.config.agent.auto_git_diff = False

    fake_client = MagicMock()
    # task_complete=Falseだが、Agent Engine側で追加課題を検出しない設定のため
    # next_prompt_requestはNoneになり、1回で終了するはず。task_completがFalseの
    # ケースでも next_prompt_request が無ければループを止めることを確認する。
    fake_client.generate.return_value = GeminiResponse(text=_json_response(task_complete=False), raw={})

    runner = AutonomousRunner(cli_app, gemini_client=fake_client)
    summary = runner.run("何かして", max_iterations=3)

    assert summary.iteration_count == 1
    assert summary.completed is True


def test_stops_on_gemini_api_error(cli_app: PromptAgentApp) -> None:
    cli_app.config.ai_backend.provider = "google_ai_studio"
    cli_app.config.ai_backend.api_key = "dummy-key"

    from promptagent.ai_backend.gemini_client import GeminiAPIError

    fake_client = MagicMock()
    fake_client.generate.side_effect = GeminiAPIError("接続失敗")

    runner = AutonomousRunner(cli_app, gemini_client=fake_client)
    summary = runner.run("何かして", max_iterations=3)

    assert summary.completed is False
    assert summary.iteration_count == 0
    assert "接続失敗" in summary.stopped_reason


def test_loops_until_no_more_followup_needed(cli_app: PromptAgentApp) -> None:
    """テスト失敗が続く限りループし、解消されたら停止することを確認する。"""
    cli_app.config.ai_backend.provider = "google_ai_studio"
    cli_app.config.ai_backend.api_key = "dummy-key"
    cli_app.config.agent.auto_run_lint = False
    cli_app.config.agent.auto_git_diff = False

    # 1回目: patch適用が失敗するようなファイルパスを与え、次プロンプトが生成される
    # ことを利用してループが継続するか確認する(パス外書き込みで失敗させる)。
    responses = [
        GeminiResponse(
            text=_json_response(
                task_complete=False,
                files=[{"path": "../outside.py", "content": "x=1", "action": "create"}],
            ),
            raw={},
        ),
        GeminiResponse(
            text=_json_response(
                task_complete=True,
                files=[{"path": "sample.py", "content": "print('fixed')", "action": "update"}],
            ),
            raw={},
        ),
    ]
    fake_client = MagicMock()
    fake_client.generate.side_effect = responses

    runner = AutonomousRunner(cli_app, gemini_client=fake_client)
    summary = runner.run("直して", max_iterations=5)

    assert summary.iteration_count == 2
    assert summary.completed is True
    assert fake_client.generate.call_count == 2
