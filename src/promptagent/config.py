"""設定管理モジュール。

`config.yaml` からユーザー設定を読み込み、型安全な `Config` オブジェクトとして
アプリケーション全体へ提供する。設定ファイルが存在しない場合はデフォルト値で
自動生成する。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIRNAME = ".promptagent"
DEFAULT_CONFIG_FILENAME = "config.yaml"


@dataclasses.dataclass(slots=True)
class ThemeConfig:
    """CLIのカラーテーマ設定。"""

    name: str = "midnight"
    accent: str = "#7C5CFF"
    background: str = "#0B0B0F"
    surface: str = "#141419"
    text: str = "#E6E6EA"
    muted: str = "#6B6B76"
    success: str = "#4ADE80"
    warning: str = "#FBBF24"
    error: str = "#F87171"


@dataclasses.dataclass(slots=True)
class KeybindingsConfig:
    """ショートカットキー設定。"""

    command_palette: str = "ctrl+p"
    quit: str = "ctrl+c"
    clear_screen: str = "ctrl+l"
    search_history: str = "ctrl+r"
    interrupt: str = "ctrl+d"
    submit: str = "enter"
    fuzzy_find: str = "ctrl+f"


@dataclasses.dataclass(slots=True)
class ContextConfig:
    """コンテキスト生成に関する設定。"""

    max_tokens: int = 12000
    max_file_size_kb: int = 256
    ignore_patterns: list[str] = dataclasses.field(
        default_factory=lambda: [
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            "dist",
            "build",
            "*.lock",
            "*.min.js",
            "*.map",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
        ]
    )
    priority_extensions: list[str] = dataclasses.field(
        default_factory=lambda: [".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java"]
    )


@dataclasses.dataclass(slots=True)
class AgentConfig:
    """Agent Engine（自動化パイプライン）の設定。"""

    auto_run_tests: bool = True
    auto_run_lint: bool = True
    auto_type_check: bool = True
    auto_git_diff: bool = True
    stop_on_test_failure: bool = False


@dataclasses.dataclass(slots=True)
class AIBackendConfig:
    """AIバックエンド(応答取得方法)に関する設定。

    - provider="human": 従来通り、Human Loop(コピー&ペースト)でAIとやり取りする。
      入出力はJSON形式になるが、AIモデル自体はPromptAgentに一切組み込まれない。
    - provider="google_ai_studio": Google AI Studio(Gemini API)を直接呼び出す。
      この場合のみ、Agent Loopによる自律的な繰り返しコーディングが利用可能になる
      (他のAI APIやローカルLLMは意図的にサポートしない)。
    """

    provider: str = "human"
    model: str = "gemini-2.0-flash"
    api_key_env: str = "GOOGLE_API_KEY"
    api_key: str = ""
    max_autonomous_iterations: int = 5
    request_timeout_seconds: float = 120.0
    temperature: float = 0.2

    @property
    def is_google_ai_studio(self) -> bool:
        """Google AI Studio(Gemini API)を利用する設定かどうか。"""
        return self.provider == "google_ai_studio"

    @property
    def autonomous_available(self) -> bool:
        """自律的なコーディングループが利用可能かどうか。

        意図的にGoogle AI Studio(Gemini API)のみで許可する。他のAI APIや
        ローカルLLMを追加しても、ここがTrueにならない限りAgent Loopは起動しない。
        """
        return self.is_google_ai_studio

    def resolve_api_key(self) -> str:
        """設定値または環境変数からAPIキーを解決する。"""
        import os

        return self.api_key or os.environ.get(self.api_key_env, "")


@dataclasses.dataclass(slots=True)
class Config:
    """PromptAgentのルート設定オブジェクト。"""

    theme: ThemeConfig = dataclasses.field(default_factory=ThemeConfig)
    keybindings: KeybindingsConfig = dataclasses.field(default_factory=KeybindingsConfig)
    context: ContextConfig = dataclasses.field(default_factory=ContextConfig)
    agent: AgentConfig = dataclasses.field(default_factory=AgentConfig)
    ai_backend: AIBackendConfig = dataclasses.field(default_factory=AIBackendConfig)
    prompt_format: str = "json"
    language: str = "ja"
    log_level: str = "INFO"
    editor: str = "code"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        """設定ファイルを読み込み、存在しなければデフォルトを生成する。"""
        config_path = path or default_config_path()
        if not config_path.exists():
            config = cls()
            config.save(config_path)
            return config

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return cls._from_dict(raw)

    def save(self, path: Path | None = None) -> None:
        """現在の設定をYAMLファイルへ保存する。"""
        config_path = path or default_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(self._to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "Config":
        theme = ThemeConfig(**raw.get("theme", {}))
        keybindings = KeybindingsConfig(**raw.get("keybindings", {}))
        context = ContextConfig(**raw.get("context", {}))
        agent = AgentConfig(**raw.get("agent", {}))
        ai_backend = AIBackendConfig(**raw.get("ai_backend", {}))
        return cls(
            theme=theme,
            keybindings=keybindings,
            context=context,
            agent=agent,
            ai_backend=ai_backend,
            prompt_format=raw.get("prompt_format", "json"),
            language=raw.get("language", "ja"),
            log_level=raw.get("log_level", "INFO"),
            editor=raw.get("editor", "code"),
        )

    def _to_dict(self) -> dict[str, Any]:
        return {
            "theme": dataclasses.asdict(self.theme),
            "keybindings": dataclasses.asdict(self.keybindings),
            "context": dataclasses.asdict(self.context),
            "agent": dataclasses.asdict(self.agent),
            "ai_backend": dataclasses.asdict(self.ai_backend),
            "prompt_format": self.prompt_format,
            "language": self.language,
            "log_level": self.log_level,
            "editor": self.editor,
        }


def default_config_path() -> Path:
    """ユーザーのホームディレクトリ配下のデフォルト設定パスを返す。"""
    return Path.home() / DEFAULT_CONFIG_DIRNAME / DEFAULT_CONFIG_FILENAME
