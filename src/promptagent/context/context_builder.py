"""コンテキスト生成エンジン。

巨大プロジェクトでもAIに送る文章量を最適化するため、関連度の高いファイルのみ
抽出し、必要に応じて要約を行ってからMarkdown形式のコンテキストを組み立てる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from promptagent.analyzer.project_analyzer import FileInfo, ProjectAnalysis
from promptagent.context.cache import SqliteCache

# 1トークン ≈ 4文字(英語)を目安とした簡易概算。日本語混在時はやや粗くなるが
# ネットワーク送信量の見積もりとしては十分実用的な精度を持つ。
_CHARS_PER_TOKEN_ESTIMATE = 4


@dataclass(slots=True)
class ContextFile:
    """コンテキストに含める1ファイル分のデータ。"""

    path: Path
    language: str
    content: str
    truncated: bool = False


@dataclass(slots=True)
class BuiltContext:
    """生成されたコンテキストの結果。"""

    files: list[ContextFile] = field(default_factory=list)
    estimated_tokens: int = 0

    def to_markdown(self) -> str:
        """ファイル群をMarkdownコードブロック形式へ変換する。"""
        sections = []
        for context_file in self.files:
            marker = " (一部省略)" if context_file.truncated else ""
            sections.append(
                f"### `{context_file.path}`{marker}\n"
                f"```{_lang_to_markdown_tag(context_file.language)}\n"
                f"{context_file.content}\n"
                f"```"
            )
        return "\n\n".join(sections)


def _lang_to_markdown_tag(language: str) -> str:
    """言語名をMarkdownコードフェンス用のタグへ変換する。"""
    mapping = {
        "Python": "python",
        "JavaScript": "javascript",
        "TypeScript": "typescript",
        "HTML": "html",
        "CSS": "css",
        "SCSS": "scss",
        "Markdown": "markdown",
        "JSON": "json",
        "YAML": "yaml",
        "Rust": "rust",
        "Go": "go",
        "Java": "java",
        "Shell": "bash",
        "SQL": "sql",
        "TOML": "toml",
    }
    return mapping.get(language, "")


class ContextBuilder:
    """関連ファイルを抽出しトークン予算内でコンテキストを構築するクラス。"""

    def __init__(
        self,
        max_tokens: int = 12000,
        cache: SqliteCache | None = None,
        priority_extensions: list[str] | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._cache = cache
        self._priority_extensions = priority_extensions or []

    def build(
        self,
        analysis: ProjectAnalysis,
        *,
        target_files: list[Path] | None = None,
        query_hint: str = "",
    ) -> BuiltContext:
        """対象ファイル(未指定なら関連度推定)からコンテキストを構築する。"""
        candidates = self._select_candidates(analysis, target_files, query_hint)
        context = BuiltContext()
        remaining_tokens = self._max_tokens

        for file_info in candidates:
            if remaining_tokens <= 0:
                break
            content, truncated = self._read_with_budget(file_info, remaining_tokens)
            if content is None:
                continue
            tokens_used = self._estimate_tokens(content)
            remaining_tokens -= tokens_used
            context.files.append(
                ContextFile(path=file_info.path, language=file_info.language, content=content, truncated=truncated)
            )

        context.estimated_tokens = self._max_tokens - remaining_tokens
        return context

    def _select_candidates(
        self,
        analysis: ProjectAnalysis,
        target_files: list[Path] | None,
        query_hint: str,
    ) -> list[FileInfo]:
        """優先順位付けされた候補ファイルのリストを返す。"""
        if target_files:
            target_set = {p.resolve() for p in target_files}
            return [f for f in analysis.files if f.path.resolve() in target_set]

        def score(file_info: FileInfo) -> tuple[int, int]:
            priority = 0
            if file_info.path.suffix.lower() in self._priority_extensions:
                priority += 10
            if query_hint and query_hint.lower() in file_info.path.name.lower():
                priority += 20
            return (-priority, file_info.size_bytes)

        return sorted(analysis.files, key=score)

    def _read_with_budget(self, file_info: FileInfo, remaining_tokens: int) -> tuple[str | None, bool]:
        """トークン予算内でファイル内容を読み込み、超過分は切り詰める。"""
        try:
            text = file_info.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, False

        max_chars = remaining_tokens * _CHARS_PER_TOKEN_ESTIMATE
        if len(text) > max_chars:
            return text[:max_chars] + "\n... (トークン予算超過のため省略)", True
        return text, False

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """文字数からトークン数を概算する。"""
        return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)
