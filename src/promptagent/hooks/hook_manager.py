"""Hookマネージャ。

BeforePrompt / AfterPrompt / BeforePatch / AfterPatch / BeforeTest / AfterTest
などのライフサイクルイベントに対して、ユーザー定義の関数（プラグイン含む）を
登録・発火できるようにする。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum, auto
from typing import Any

logger = logging.getLogger("promptagent.hooks")


class HookEvent(Enum):
    """フックが発火するライフサイクルイベント種別。"""

    BEFORE_PROMPT = auto()
    AFTER_PROMPT = auto()
    BEFORE_PATCH = auto()
    AFTER_PATCH = auto()
    BEFORE_TEST = auto()
    AFTER_TEST = auto()
    BEFORE_LINT = auto()
    AFTER_LINT = auto()
    BEFORE_COMMIT = auto()
    AFTER_COMMIT = auto()


HookCallback = Callable[[dict[str, Any]], None]


class HookManager:
    """イベントごとにコールバックを登録・発火するクラス。"""

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookCallback]] = {event: [] for event in HookEvent}

    def register(self, event: HookEvent, callback: HookCallback) -> None:
        """指定イベントへコールバックを登録する。"""
        self._hooks[event].append(callback)

    def unregister(self, event: HookEvent, callback: HookCallback) -> None:
        """登録済みコールバックを解除する。"""
        if callback in self._hooks[event]:
            self._hooks[event].remove(callback)

    def fire(self, event: HookEvent, context: dict[str, Any] | None = None) -> None:
        """指定イベントに登録された全コールバックを順番に実行する。"""
        payload = context or {}
        for callback in self._hooks[event]:
            try:
                callback(payload)
            except Exception:
                logger.exception("フック実行中に例外が発生しました: event=%s", event)

    def has_hooks(self, event: HookEvent) -> bool:
        """指定イベントにコールバックが1件以上登録されているか。"""
        return len(self._hooks[event]) > 0
