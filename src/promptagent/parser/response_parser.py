"""Response Parser。

AIからの回答テキスト(Markdown形式想定)を解析し、コードブロック・
対象ファイル名・TODO・修正点の説明・実行すべきコマンド・注意事項を
構造化して抽出する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CODE_BLOCK_PATTERN = re.compile(
    r"```(?P<lang>[a-zA-Z0-9_+\-]*)\n(?P<body>.*?)```", re.DOTALL
)
_FILE_HEADER_PATTERNS = [
    re.compile(r"^\s*(?:#{1,6}\s*)?(?:ファイル|File)\s*[:：]\s*`?([^\s`]+)`?\s*$", re.MULTILINE),
    re.compile(r"^\s*\*\*`?([^\s`*]+\.[a-zA-Z0-9]+)`?\*\*\s*$", re.MULTILINE),
    re.compile(r"^\s*(?:#{1,6}\s*)?`([^\s`]+\.[a-zA-Z0-9]+)`\s*$", re.MULTILINE),
]
_TODO_PATTERN = re.compile(r"^\s*[-*]?\s*TODO\s*[:：]?\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_NOTE_PATTERN = re.compile(r"^\s*[-*]?\s*(?:注意|Note|NOTE)\s*[:：]\s*(.+)$", re.MULTILINE)
_BASH_LANGS = {"bash", "sh", "shell", "zsh", "console", "powershell", "ps1", "cmd"}


@dataclass(slots=True)
class ExtractedCodeBlock:
    """1つのコードブロックとその推定対象ファイル。"""

    language: str
    content: str
    filename: str | None = None
    start_index: int = 0


@dataclass(slots=True)
class ParsedResponse:
    """AI回答の解析結果全体。"""

    code_blocks: list[ExtractedCodeBlock] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def file_patches(self) -> dict[str, str]:
        """ファイル名が判明しているコードブロックのみを辞書化する。"""
        return {
            block.filename: block.content
            for block in self.code_blocks
            if block.filename and block.language.lower() not in _BASH_LANGS
        }


class ResponseParser:
    """AI回答テキストを解析し `ParsedResponse` を構築するクラス。"""

    def parse(self, text: str) -> ParsedResponse:
        """AI回答全文を解析する。"""
        result = ParsedResponse(raw_text=text)

        for match in _CODE_BLOCK_PATTERN.finditer(text):
            language = match.group("lang").strip()
            body = match.group("body")
            filename = self._infer_filename(text, match.start(), body, language)

            block = ExtractedCodeBlock(
                language=language, content=body.rstrip("\n"), filename=filename, start_index=match.start()
            )
            result.code_blocks.append(block)

            if language.lower() in _BASH_LANGS:
                result.commands.extend(
                    line.strip() for line in body.strip().splitlines() if line.strip() and not line.strip().startswith("#")
                )

        result.todos = [m.strip() for m in _TODO_PATTERN.findall(text)]
        result.notes = [m.strip() for m in _NOTE_PATTERN.findall(text)]
        return result

    def _infer_filename(self, full_text: str, block_start: int, body: str, language: str) -> str | None:
        """コードブロック直前の見出しやコメントからファイル名を推定する。"""
        preceding_text = full_text[:block_start]
        preceding_lines = preceding_text.splitlines()[-5:]
        preceding_block = "\n".join(preceding_lines)

        for pattern in _FILE_HEADER_PATTERNS:
            matches = pattern.findall(preceding_block)
            if matches:
                return matches[-1]

        first_line = body.strip().splitlines()[0] if body.strip() else ""
        comment_match = re.match(r"^\s*(?:#|//|<!--)\s*([^\s]+\.[a-zA-Z0-9]+)", first_line)
        if comment_match:
            return comment_match.group(1)

        return None
