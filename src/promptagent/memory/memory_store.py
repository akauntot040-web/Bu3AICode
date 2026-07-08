"""Memoryモジュール。

セッション情報・会話履歴(プロンプト/回答ペア)・プロジェクト履歴・
最近使ったプロジェクト一覧を永続化する。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_MEMORY_ROOT = Path.home() / ".promptagent" / "memory"
_RECENT_PROJECTS_FILE = _MEMORY_ROOT / "recent_projects.json"
_MAX_RECENT_PROJECTS = 20


@dataclass(slots=True)
class ConversationTurn:
    """1往復分の会話履歴。"""

    prompt_text: str
    response_text: str
    timestamp: float = field(default_factory=time.time)


@dataclass(slots=True)
class Session:
    """1回のPromptAgent起動〜終了までのセッション情報。"""

    session_id: str
    project_root: str
    started_at: float
    turns: list[ConversationTurn] = field(default_factory=list)

    def to_dict(self) -> dict:
        """JSON保存用の辞書表現へ変換する。"""
        return {
            "session_id": self.session_id,
            "project_root": self.project_root,
            "started_at": self.started_at,
            "turns": [
                {"prompt_text": t.prompt_text, "response_text": t.response_text, "timestamp": t.timestamp}
                for t in self.turns
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """辞書からセッションを復元する。"""
        return cls(
            session_id=data["session_id"],
            project_root=data["project_root"],
            started_at=data["started_at"],
            turns=[
                ConversationTurn(
                    prompt_text=t["prompt_text"], response_text=t["response_text"], timestamp=t["timestamp"]
                )
                for t in data.get("turns", [])
            ],
        )

    @classmethod
    def create(cls, project_root: str) -> "Session":
        """新規セッションを生成する。"""
        return cls(session_id=str(uuid.uuid4()), project_root=project_root, started_at=time.time())


class MemoryStore:
    """セッション履歴と最近使ったプロジェクト一覧を管理するクラス。"""

    def __init__(self, memory_root: Path | None = None) -> None:
        self._memory_root = memory_root or _MEMORY_ROOT
        self._memory_root.mkdir(parents=True, exist_ok=True)

    def save_session(self, session: Session) -> Path:
        """セッションをJSONファイルとして保存する。"""
        session_path = self._memory_root / f"session_{session.session_id}.json"
        session_path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._touch_recent_project(session.project_root)
        return session_path

    def load_session(self, session_id: str) -> Session | None:
        """指定IDのセッションを読み込む。"""
        session_path = self._memory_root / f"session_{session_id}.json"
        if not session_path.exists():
            return None
        data = json.loads(session_path.read_text(encoding="utf-8"))
        return Session.from_dict(data)

    def list_sessions(self, limit: int = 20) -> list[Session]:
        """保存済みセッションを新しい順に取得する。"""
        session_files = sorted(
            self._memory_root.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        sessions = []
        for path in session_files[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(Session.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions

    def _touch_recent_project(self, project_root: str) -> None:
        """最近使ったプロジェクト一覧を更新する。"""
        recent = self.list_recent_projects()
        recent = [p for p in recent if p != project_root]
        recent.insert(0, project_root)
        recent = recent[:_MAX_RECENT_PROJECTS]
        _RECENT_PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_PROJECTS_FILE.write_text(json.dumps(recent, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_recent_projects(self) -> list[str]:
        """最近使ったプロジェクトパスの一覧を取得する。"""
        if not _RECENT_PROJECTS_FILE.exists():
            return []
        try:
            return json.loads(_RECENT_PROJECTS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
