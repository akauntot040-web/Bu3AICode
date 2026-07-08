"""ResponseParserの単体テスト。"""

from __future__ import annotations

from promptagent.parser.response_parser import ResponseParser


def test_extracts_code_block_with_filename_header() -> None:
    text = (
        "修正内容は以下の通りです。\n\n"
        "### `src/app/main.py`\n"
        "```python\n"
        "print('hello')\n"
        "```\n"
    )
    parsed = ResponseParser().parse(text)
    assert len(parsed.code_blocks) == 1
    assert parsed.code_blocks[0].filename == "src/app/main.py"
    assert "print('hello')" in parsed.code_blocks[0].content


def test_extracts_bash_commands() -> None:
    text = "以下を実行してください。\n```bash\npip install requests\npytest -q\n```\n"
    parsed = ResponseParser().parse(text)
    assert "pip install requests" in parsed.commands
    assert "pytest -q" in parsed.commands


def test_extracts_todos_and_notes() -> None:
    text = "- TODO: エラーハンドリングを追加する\n- 注意: 本番環境では動作未確認です\n"
    parsed = ResponseParser().parse(text)
    assert any("エラーハンドリング" in todo for todo in parsed.todos)
    assert any("本番環境" in note for note in parsed.notes)


def test_file_patches_excludes_bash_blocks() -> None:
    text = (
        "### `app.py`\n```python\nx = 1\n```\n\n"
        "```bash\necho hi\n```\n"
    )
    parsed = ResponseParser().parse(text)
    assert "app.py" in parsed.file_patches
    assert len(parsed.file_patches) == 1
