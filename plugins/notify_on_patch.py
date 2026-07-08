"""サンプルプラグイン: パッチ適用完了を通知する。

`AFTER_PATCH` フックを利用し、適用結果を分かりやすくログへ出力する。
プラグインは `plugins/` ディレクトリへPythonファイルを置くだけで
自動的にロードされる。
"""

from __future__ import annotations

from promptagent.hooks.hook_manager import HookEvent, HookManager


def register(hook_manager: HookManager) -> None:
    """プラグインのエントリポイント。"""

    def on_after_patch(context: dict) -> None:
        batch = context.get("batch")
        if batch is None:
            return
        succeeded = len(batch.succeeded)
        failed = len(batch.failed)
        print(f"[notify_on_patch] パッチ適用完了: 成功={succeeded} 失敗={failed}")

    hook_manager.register(HookEvent.AFTER_PATCH, on_after_patch)
