"""Pluginマネージャ。

`plugins/` ディレクトリ配下のPythonモジュールを動的にロードし、
`register(hook_manager)` 関数を呼び出すことでフックへコールバックを
登録させる。プラグインはPromptAgent本体に手を加えず機能拡張できる。
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from promptagent.hooks.hook_manager import HookManager

logger = logging.getLogger("promptagent.plugins")

_ENTRY_POINT_FUNCTION = "register"


@dataclass(slots=True)
class LoadedPlugin:
    """ロード済みプラグインの情報。"""

    name: str
    path: Path
    module: ModuleType


class PluginManager:
    """プラグインディレクトリを走査し動的ロードするクラス。"""

    def __init__(self, plugin_dir: Path) -> None:
        self._plugin_dir = plugin_dir
        self._loaded: list[LoadedPlugin] = []

    @property
    def loaded_plugins(self) -> list[LoadedPlugin]:
        """ロード済みプラグイン一覧を返す。"""
        return list(self._loaded)

    def discover(self) -> list[Path]:
        """プラグインディレクトリ内の *.py ファイルを列挙する。"""
        if not self._plugin_dir.exists():
            return []
        return sorted(p for p in self._plugin_dir.glob("*.py") if not p.name.startswith("_"))

    def load_all(self, hook_manager: HookManager) -> list[LoadedPlugin]:
        """発見した全プラグインをロードし `register()` を呼び出す。"""
        self._loaded.clear()
        for plugin_path in self.discover():
            plugin = self._load_single(plugin_path, hook_manager)
            if plugin:
                self._loaded.append(plugin)
        return self._loaded

    def _load_single(self, plugin_path: Path, hook_manager: HookManager) -> LoadedPlugin | None:
        """1つのプラグインファイルをロードする。"""
        module_name = f"promptagent_plugin_{plugin_path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, plugin_path)
            if spec is None or spec.loader is None:
                logger.error("プラグインのロードに失敗しました: %s", plugin_path)
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            register_func = getattr(module, _ENTRY_POINT_FUNCTION, None)
            if callable(register_func):
                register_func(hook_manager)
            else:
                logger.warning(
                    "プラグイン %s に register(hook_manager) 関数が見つかりません", plugin_path.name
                )

            return LoadedPlugin(name=plugin_path.stem, path=plugin_path, module=module)
        except Exception:
            logger.exception("プラグイン読み込み中に例外が発生しました: %s", plugin_path)
            return None


_EXAMPLE_PLUGIN_TEMPLATE = '''"""PromptAgentプラグインのサンプルテンプレート。

`register(hook_manager)` を実装することで、任意のライフサイクルイベントに
処理を追加できます。
"""

from promptagent.hooks.hook_manager import HookEvent, HookManager


def register(hook_manager: HookManager) -> None:
    """プラグインのエントリポイント。フックへコールバックを登録する。"""

    def on_after_prompt(context: dict) -> None:
        print("[example_plugin] プロンプトが生成されました")

    hook_manager.register(HookEvent.AFTER_PROMPT, on_after_prompt)
'''


def write_example_plugin(plugin_dir: Path) -> Path:
    """サンプルプラグインファイルを生成する(初回セットアップ用)。"""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    example_path = plugin_dir / "example_plugin.py"
    if not example_path.exists():
        example_path.write_text(_EXAMPLE_PLUGIN_TEMPLATE, encoding="utf-8")
    return example_path
