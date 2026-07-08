"""ロギング初期化モジュール。

`logs/` ディレクトリへ操作ログ・クラッシュログ・Gitログを分割して出力する。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    """ロガーを初期化し、ファイル+コンソールへ出力するよう設定する。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d")

    root_logger = logging.getLogger("promptagent")
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    operation_handler = logging.FileHandler(
        log_dir / f"operations_{timestamp}.log", encoding="utf-8"
    )
    operation_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    operation_handler.setLevel(logging.DEBUG)
    root_logger.addHandler(operation_handler)

    crash_handler = logging.FileHandler(log_dir / "crash.log", encoding="utf-8")
    crash_handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    crash_handler.setLevel(logging.ERROR)
    root_logger.addHandler(crash_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    console_handler.setLevel(logging.WARNING)
    root_logger.addHandler(console_handler)

    return root_logger


def get_git_logger(log_dir: Path) -> logging.Logger:
    """Git操作専用のロガーを返す。"""
    logger = logging.getLogger("promptagent.git")
    if not logger.handlers:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "git.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger
