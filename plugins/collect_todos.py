"""サンプルプラグイン: プロンプト生成前にプロジェクト内のTODOコメントを検出する。

`BEFORE_PROMPT` フックの利用例。実際の収集ロジックは簡易的なものだが、
プラグインからプロジェクトファイルへアクセスして情報を集め、ログへ
出力するパターンを示している。
"""

from __future__ import annotations

import re
from pathlib import Path

from promptagent.hooks.hook_manager import HookEvent, HookManager

_TODO_PATTERN = re.compile(r"#\s*TODO[:：]?\s*(.+)")


def register(hook_manager: HookManager) -> None:
    """プラグインのエントリポイント。"""

    def on_before_prompt(context: dict) -> None:
        project_root = context.get("project_root")
        if not project_root:
            return
        todo_count = 0
        for py_file in Path(project_root).rglob("*.py"):
            if ".venv" in py_file.parts or "node_modules" in py_file.parts:
                continue
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            todo_count += len(_TODO_PATTERN.findall(text))
        if todo_count:
            print(f"[collect_todos] プロジェクト内に{todo_count}件のTODOコメントがあります")

    hook_manager.register(HookEvent.BEFORE_PROMPT, on_before_prompt)
