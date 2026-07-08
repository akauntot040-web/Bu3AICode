"""Terminal実行モジュール。

任意のシェルコマンドを実行し、標準出力・標準エラー・終了コードを取得する。
Live表示向けにストリーミング実行も提供する。
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class CommandResult:
    """コマンド実行結果。"""

    command: str
    stdout: str
    stderr: str
    exit_code: int
    succeeded: bool


class CommandExecutor:
    """シェルコマンドの実行を担当するクラス。"""

    def __init__(self, cwd: Path, timeout_seconds: float = 300.0) -> None:
        self._cwd = cwd
        self._timeout_seconds = timeout_seconds

    def run(self, command: str) -> CommandResult:
        """コマンドを実行し完了を待って結果を返す。"""
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=str(self._cwd),
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
            return CommandResult(
                command=command,
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                succeeded=completed.returncode == 0,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                command=command,
                stdout=exc.stdout or "",
                stderr=f"タイムアウト({self._timeout_seconds}秒)しました: {exc}",
                exit_code=-1,
                succeeded=False,
            )
        except OSError as exc:
            return CommandResult(command=command, stdout="", stderr=str(exc), exit_code=-1, succeeded=False)

    def run_streaming(self, command: str, on_line: Callable[[str], None]) -> CommandResult:
        """コマンドを実行しながら1行ごとにコールバックへ渡す(リアルタイム表示用)。"""
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=str(self._cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            on_line(line.rstrip("\n"))
        process.wait()
        full_output = "".join(lines)
        return CommandResult(
            command=command,
            stdout=full_output,
            stderr="",
            exit_code=process.returncode or 0,
            succeeded=(process.returncode == 0),
        )

    def iter_output(self, command: str) -> Iterator[str]:
        """コマンド出力を1行ずつ生成するジェネレータ。"""
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=str(self._cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            yield line.rstrip("\n")
        process.wait()
