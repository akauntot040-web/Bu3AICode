"""json_schemaモジュールの単体テスト。"""

from __future__ import annotations

import json

import pytest

from promptagent.prompt.json_schema import (
    JsonContextFile,
    JsonPromptRequest,
    JsonResponseParseError,
    JsonResponseParser,
)


def test_prompt_request_to_dict_includes_schema() -> None:
    request = JsonPromptRequest(instruction="バグを直して", project_name="app")
    payload = request.to_dict()
    assert payload["instruction"] == "バグを直して"
    assert "response_json_schema" in payload


def test_prompt_request_omits_empty_optional_fields() -> None:
    request = JsonPromptRequest(instruction="テスト")
    payload = request.to_dict()
    assert "git_diff" not in payload
    assert "test_output" not in payload


def test_prompt_request_includes_context_files() -> None:
    request = JsonPromptRequest(
        instruction="テスト",
        context_files=[JsonContextFile(path="a.py", language="Python", content="x=1")],
    )
    payload = request.to_dict()
    assert payload["context_files"][0]["path"] == "a.py"


def test_parser_handles_plain_json() -> None:
    raw = json.dumps(
        {
            "summary": "修正しました",
            "files": [{"path": "app.py", "content": "print(1)", "action": "update"}],
            "commands": ["pytest"],
            "todos": [],
            "notes": [],
            "task_complete": True,
        }
    )
    parsed = JsonResponseParser().parse(raw)
    assert parsed.summary == "修正しました"
    assert parsed.file_patches == {"app.py": "print(1)"}
    assert parsed.task_complete is True


def test_parser_handles_json_wrapped_in_code_fence() -> None:
    raw = (
        "```json\n"
        '{"summary": "ok", "files": [], "commands": [], "todos": [], "notes": [], "task_complete": false}\n'
        "```\n"
    )
    parsed = JsonResponseParser().parse(raw)
    assert parsed.summary == "ok"
    assert parsed.task_complete is False


def test_parser_handles_json_with_surrounding_prose() -> None:
    raw = (
        "以下が回答です。\n\n"
        '{"summary": "done", "files": [], "commands": [], "todos": ["確認してください"], '
        '"notes": [], "task_complete": true}\n\n'
        "以上です。"
    )
    parsed = JsonResponseParser().parse(raw)
    assert parsed.summary == "done"
    assert parsed.todos == ["確認してください"]


def test_parser_raises_on_invalid_json() -> None:
    with pytest.raises(JsonResponseParseError):
        JsonResponseParser().parse("これはJSONではありません。")


def test_parser_tolerates_missing_optional_fields() -> None:
    raw = '{"files": [{"path": "a.py", "content": "x"}]}'
    parsed = JsonResponseParser().parse(raw)
    assert parsed.file_patches == {"a.py": "x"}
    assert parsed.task_complete is False
