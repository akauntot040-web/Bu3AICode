"""PromptAgentAppのJSON形式プロンプト生成・応答処理の統合テスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from promptagent.cli import PromptAgentApp


@pytest.fixture
def cli_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PromptAgentApp:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sample.py").write_text("print('hi')\n", encoding="utf-8")
    app = PromptAgentApp(tmp_path)
    app.bootstrap()
    yield app
    app.cache.close()


def test_default_prompt_format_is_json(cli_app: PromptAgentApp) -> None:
    assert cli_app.config.prompt_format == "json"


def test_build_prompt_request_produces_valid_json(cli_app: PromptAgentApp) -> None:
    _request, prompt_text = cli_app.build_prompt_request("sample.pyを直して")
    payload = json.loads(prompt_text)
    assert payload["instruction"] == "sample.pyを直して"
    assert "response_json_schema" in payload
    assert any(f["path"] == "sample.py" for f in payload.get("context_files", []))


def test_process_ai_response_applies_json_response(cli_app: PromptAgentApp) -> None:
    request, prompt_text = cli_app.build_prompt_request("sample.pyを更新して")
    response_text = json.dumps(
        {
            "summary": "更新しました",
            "files": [{"path": "sample.py", "content": "print('updated')", "action": "update"}],
            "commands": [],
            "todos": [],
            "notes": [],
            "task_complete": True,
        }
    )
    cycle_result = cli_app.process_ai_response(prompt_text, response_text, request)

    assert (cli_app.project_root / "sample.py").read_text(encoding="utf-8") == "print('updated')"
    assert cycle_result.task_complete is True
    assert cycle_result.json_response is not None
    assert cycle_result.json_response.summary == "更新しました"
