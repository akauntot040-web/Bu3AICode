"""Lint / フォーマット / 型チェックランナー。

ruff・flake8・black・mypy・eslint・prettierなど、プロジェクトに存在する
設定ファイルや依存関係から適切なツールを自動選択して実行する。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from promptagent.terminal.executor import CommandExecutor, CommandResult

_LINT_TOOLS: list[tuple[str, str, str]] = [
    ("ruff.toml", "ruff", "ruff check ."),
    (".flake8", "flake8", "flake8 ."),
    ("pyproject.toml", "black --check", "black --check ."),
    ("mypy.ini", "mypy", "mypy ."),
    (".eslintrc.json", "eslint", "npx eslint ."),
    (".eslintrc.js", "eslint", "npx eslint ."),
    (".prettierrc", "prettier --check", "npx prettier --check ."),
]


@dataclass(slots=True)
class LintOutcome:
    """Lintツール1つの実行結果。"""

    tool_name: str
    command: str
    result: CommandResult

    @property
    def is_clean(self) -> bool:
        """指摘事項なしかどうか。"""
        return self.result.succeeded


class LintRunner:
    """プロジェクトに応じてLint/型チェックツールを実行するクラス。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._executor = CommandExecutor(cwd=project_root)

    def detect_tools(self) -> list[tuple[str, str]]:
        """利用可能なLintツール(名称, コマンド)を検出する。重複ツール名は除去。"""
        seen: set[str] = set()
        detected = []
        for marker, name, command in _LINT_TOOLS:
            if (self._project_root / marker).exists() and name not in seen:
                detected.append((name, command))
                seen.add(name)
        return detected

    def run_all(self) -> list[LintOutcome]:
        """検出された全ツールを実行する。"""
        outcomes = []
        for name, command in self.detect_tools():
            result = self._executor.run(command)
            outcomes.append(LintOutcome(tool_name=name, command=command, result=result))
        return outcomes

    def run(self, command: str, tool_name: str = "custom") -> LintOutcome:
        """指定コマンドでLintツールを実行する。"""
        result = self._executor.run(command)
        return LintOutcome(tool_name=tool_name, command=command, result=result)
