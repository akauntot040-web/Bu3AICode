"""テストランナー。

プロジェクトの言語構成に応じて pytest / unittest / Jest / Cargo test / Go test
などを自動選択・自動実行し、結果を構造化して返す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from promptagent.terminal.executor import CommandExecutor, CommandResult

_TEST_RUNNERS: list[tuple[str, str, str]] = [
    # (判定用マニフェスト/マーカー, 表示名, 実行コマンド)
    ("pyproject.toml", "pytest", "python -m pytest -q"),
    ("pytest.ini", "pytest", "python -m pytest -q"),
    ("setup.py", "unittest", "python -m unittest discover -v"),
    ("package.json", "jest", "npx jest --colors=false"),
    ("Cargo.toml", "cargo test", "cargo test"),
    ("go.mod", "go test", "go test ./..."),
]

_PYTEST_SUMMARY_PATTERN = re.compile(
    r"(?P<passed>\d+) passed|(?P<failed>\d+) failed|(?P<errors>\d+) error"
)


@dataclass(slots=True)
class TestOutcome:
    """テスト実行結果の要約。"""

    runner_name: str
    command: str
    raw_result: CommandResult
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    failing_tests: list[str] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        """全テストが成功したかどうか。"""
        return self.raw_result.succeeded and self.failed_count == 0 and self.error_count == 0


class TestRunner:
    """プロジェクト種別に応じてテストを自動実行するクラス。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._executor = CommandExecutor(cwd=project_root)

    def detect_runners(self) -> list[tuple[str, str]]:
        """利用可能なテストランナー(表示名, コマンド)の一覧を検出する。"""
        detected = []
        for marker, name, command in _TEST_RUNNERS:
            if (self._project_root / marker).exists():
                detected.append((name, command))
        return detected

    def run_all(self) -> list[TestOutcome]:
        """検出された全ランナーでテストを実行する。"""
        outcomes = []
        for name, command in self.detect_runners():
            result = self._executor.run(command)
            outcomes.append(self._summarize(name, command, result))
        return outcomes

    def run(self, command: str, runner_name: str = "custom") -> TestOutcome:
        """指定したコマンドでテストを実行する。"""
        result = self._executor.run(command)
        return self._summarize(runner_name, command, result)

    def _summarize(self, runner_name: str, command: str, result: CommandResult) -> TestOutcome:
        """テスト出力からpass/fail件数と失敗テスト名を抽出する。"""
        combined_output = result.stdout + "\n" + result.stderr
        passed = failed = errors = 0

        for match in _PYTEST_SUMMARY_PATTERN.finditer(combined_output):
            if match.group("passed"):
                passed = int(match.group("passed"))
            if match.group("failed"):
                failed = int(match.group("failed"))
            if match.group("errors"):
                errors = int(match.group("errors"))

        failing_tests = re.findall(r"^FAILED (\S+)", combined_output, re.MULTILINE)
        failing_tests += re.findall(r"✕\s+(.+)", combined_output)

        return TestOutcome(
            runner_name=runner_name,
            command=command,
            raw_result=result,
            passed_count=passed,
            failed_count=failed,
            error_count=errors,
            failing_tests=failing_tests,
        )
