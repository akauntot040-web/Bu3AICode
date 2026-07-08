"""`/auto` コマンドのCLIレベルテスト。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from promptagent.ai_backend.gemini_client import GeminiResponse
from promptagent.cli import PromptAgentApp


@pytest.fixture
def cli_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PromptAgentApp:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sample.py").write_text("print('hi')\n", encoding="utf-8")
    app = PromptAgentApp(tmp_path)
    app.bootstrap()
    yield app
    app.cache.close()


def test_auto_command_blocked_without_google_ai_studio(cli_app: PromptAgentApp, capsys) -> None:
    cli_app.config.ai_backend.provider = "human"
    result = cli_app._cmd_auto("sample.pyを直して")
    assert result is True  # ループ継続(致命的エラーではない)


def test_auto_command_requires_instruction(cli_app: PromptAgentApp) -> None:
    cli_app.config.ai_backend.provider = "google_ai_studio"
    cli_app.config.ai_backend.api_key = "dummy"
    result = cli_app._cmd_auto("")
    assert result is True


def test_auto_command_runs_autonomous_loop(cli_app: PromptAgentApp) -> None:
    cli_app.config.ai_backend.provider = "google_ai_studio"
    cli_app.config.ai_backend.api_key = "dummy-key"

    fake_response = GeminiResponse(
        text=json.dumps(
            {
                "summary": "修正しました",
                "files": [{"path": "sample.py", "content": "print('fixed')", "action": "update"}],
                "commands": [],
                "todos": [],
                "notes": [],
                "task_complete": True,
            }
        ),
        raw={},
    )

    with patch("promptagent.ai_backend.gemini_client.GeminiClient.generate", return_value=fake_response):
        result = cli_app._cmd_auto("sample.pyを直して")

    assert result is True
    assert (cli_app.project_root / "sample.py").read_text(encoding="utf-8") == "print('fixed')"
