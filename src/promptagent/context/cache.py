"""SQLiteによる高速キャッシュ層。

プロジェクト解析結果・ファイル要約・コンテキスト生成結果をキャッシュし、
巨大プロジェクトでも高速に再起動できるようにする。ファイルの
更新時刻(mtime)とサイズをキーにキャッシュの有効性を判定する。
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS project_analysis (
    root TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS file_summary (
    file_path TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    size_bytes INTEGER NOT NULL,
    summary TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS session_memory (
    session_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""


class SqliteCache:
    """プロジェクト単位のSQLiteキャッシュを管理するクラス。"""

    def __init__(self, cache_path: Path) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(cache_path))
        self._connection.executescript(_SCHEMA)
        self._connection.commit()

    def close(self) -> None:
        """DB接続をクローズする。"""
        self._connection.close()

    def __enter__(self) -> "SqliteCache":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- プロジェクト解析キャッシュ -----------------------------------------

    def get_project_analysis(self, root: str) -> dict[str, Any] | None:
        """キャッシュされたプロジェクト解析結果を取得する。"""
        cursor = self._connection.execute(
            "SELECT payload FROM project_analysis WHERE root = ?", (root,)
        )
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None

    def set_project_analysis(self, root: str, payload: dict[str, Any]) -> None:
        """プロジェクト解析結果をキャッシュへ保存する。"""
        self._connection.execute(
            "INSERT INTO project_analysis (root, payload, updated_at) VALUES (?, ?, ?)\n"
            "ON CONFLICT(root) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (root, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self._connection.commit()

    # -- ファイル要約キャッシュ -----------------------------------------------

    def get_file_summary(self, file_path: str, mtime: float, size_bytes: int) -> str | None:
        """ファイルが変更されていなければキャッシュ済み要約を返す。"""
        cursor = self._connection.execute(
            "SELECT mtime, size_bytes, summary FROM file_summary WHERE file_path = ?",
            (file_path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        cached_mtime, cached_size, summary = row
        if cached_mtime == mtime and cached_size == size_bytes:
            return summary
        return None

    def set_file_summary(self, file_path: str, mtime: float, size_bytes: int, summary: str) -> None:
        """ファイル要約をキャッシュへ保存する。"""
        self._connection.execute(
            "INSERT INTO file_summary (file_path, mtime, size_bytes, summary, updated_at) "
            "VALUES (?, ?, ?, ?, ?)\n"
            "ON CONFLICT(file_path) DO UPDATE SET mtime = excluded.mtime, "
            "size_bytes = excluded.size_bytes, summary = excluded.summary, updated_at = excluded.updated_at",
            (file_path, mtime, size_bytes, summary, time.time()),
        )
        self._connection.commit()

    # -- セッションメモリ -----------------------------------------------------

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """セッション情報を取得する。"""
        cursor = self._connection.execute(
            "SELECT payload FROM session_memory WHERE session_id = ?", (session_id,)
        )
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None

    def set_session(self, session_id: str, payload: dict[str, Any]) -> None:
        """セッション情報を保存する。"""
        self._connection.execute(
            "INSERT INTO session_memory (session_id, payload, updated_at) VALUES (?, ?, ?)\n"
            "ON CONFLICT(session_id) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at",
            (session_id, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        self._connection.commit()

    def list_recent_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        """直近のセッション一覧を新しい順で取得する。"""
        cursor = self._connection.execute(
            "SELECT session_id, payload, updated_at FROM session_memory "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        results = []
        for session_id, payload, updated_at in cursor.fetchall():
            data = json.loads(payload)
            data["session_id"] = session_id
            data["updated_at"] = updated_at
            results.append(data)
        return results


def default_cache_path(project_root: Path) -> Path:
    """プロジェクトごとのデフォルトキャッシュファイルパスを返す。"""
    cache_dir = Path.home() / ".promptagent" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = str(abs(hash(str(project_root.resolve()))))
    return cache_dir / f"{digest}.sqlite3"
