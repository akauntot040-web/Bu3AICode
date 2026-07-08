"""PromptEngineの単体テスト。

生成されるフォーマット指示が、実際にResponseParserが検出できる
形式の実例を含んでいることを保証する(指示と実装がズレないようにする)。
"""

from __future__ import annotations

from promptagent.parser.response_parser import ResponseParser
from promptagent.prompt.prompt_engine import PromptEngine, PromptRequest


def test_build_includes_instruction_and_project_name() -> None:
    request = PromptRequest(instruction="バグを修正してください", project_name="myproj")
    prompt_text = PromptEngine().build(request)
    assert "myproj" in prompt_text
    assert "バグを修正してください" in prompt_text


def test_format_instructions_example_is_parseable_by_response_parser() -> None:
    """プロンプト内の「記述例」自体が、ResponseParserで正しく解析できることを検証する。

    これにより、指示文とパーサーの実装がズレて「指示通り書いてもパースされない」
    という事態を防ぐ。
    """
    prompt_text = PromptEngine().build(PromptRequest(instruction="テスト"))

    # プロンプト内の例示コードブロック(4連バックティックで囲まれた説明用ブロック)を
    # 取り出し、その中身だけを実際にResponseParserへ通す。
    start_marker = "````markdown\n"
    end_marker = "\n````"
    start = prompt_text.index(start_marker) + len(start_marker)
    end = prompt_text.index(end_marker, start)
    example_block = prompt_text[start:end]

    parsed = ResponseParser().parse(example_block)
    assert len(parsed.code_blocks) == 1
    assert parsed.code_blocks[0].filename == "src/app/main.py"
    assert "def main" in parsed.code_blocks[0].content


def test_format_instructions_mention_all_required_rules() -> None:
    prompt_text = PromptEngine().build(PromptRequest(instruction="テスト"))
    assert "TODO:" in prompt_text
    assert "```bash" in prompt_text
    assert "省略" in prompt_text
    assert "完全な内容" in prompt_text


def test_optional_sections_included_only_when_present() -> None:
    request_without_extras = PromptRequest(instruction="テスト")
    prompt_without = PromptEngine().build(request_without_extras)
    assert "Git差分" not in prompt_without
    assert "テスト結果" not in prompt_without

    request_with_extras = PromptRequest(
        instruction="テスト", git_diff="diff --git a b", test_output="1 failed"
    )
    prompt_with = PromptEngine().build(request_with_extras)
    assert "Git差分" in prompt_with
    assert "テスト結果" in prompt_with
