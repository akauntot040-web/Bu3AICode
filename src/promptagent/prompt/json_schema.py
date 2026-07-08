"""JSON形式の入出力スキーマ定義。

従来のMarkdown+正規表現によるパースは、AIの出力ゆらぎに弱いという弱点があった。
`prompt_format: json` を使うと、リクエスト・レスポンスの両方を厳密な構造化
JSONとしてやり取りできる。レスポンスのパースは正規表現ではなく`json.loads`と
スキーマ検証のみで行われるため、堅牢性が大きく向上する。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# AIへ提示する「期待する出力スキーマ」。プロンプトへそのまま埋め込む。
RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "変更内容の要約(日本語で1〜3文)"},
        "files": {
            "type": "array",
            "description": "作成・更新するファイルの一覧",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "プロジェクトルートからの相対パス"},
                    "content": {"type": "string", "description": "ファイルの完全な内容(省略禁止)"},
                    "action": {"type": "string", "enum": ["create", "update"]},
                },
                "required": ["path", "content", "action"],
            },
        },
        "commands": {
            "type": "array",
            "description": "実行してほしいシェルコマンドの一覧",
            "items": {"type": "string"},
        },
        "todos": {
            "type": "array",
            "description": "対応しきれなかった残作業の一覧",
            "items": {"type": "string"},
        },
        "notes": {
            "type": "array",
            "description": "注意事項・補足の一覧",
            "items": {"type": "string"},
        },
        "task_complete": {
            "type": "boolean",
            "description": "指示された作業が完全に完了したとAIが判断していればtrue",
        },
    },
    "required": ["summary", "files", "commands", "todos", "notes", "task_complete"],
}


@dataclass(slots=True)
class JsonContextFile:
    """JSONリクエストに含める1ファイル分のコンテキスト。"""

    path: str
    language: str
    content: str
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON変換用の辞書表現を返す。"""
        return {
            "path": self.path,
            "language": self.language,
            "content": self.content,
            "truncated": self.truncated,
        }


@dataclass(slots=True)
class JsonPromptRequest:
    """AIへ送るJSON形式のリクエスト全体。"""

    instruction: str
    project_name: str = ""
    git_diff: str = ""
    git_status_summary: str = ""
    test_output: str = ""
    lint_output: str = ""
    error_output: str = ""
    context_files: list[JsonContextFile] = field(default_factory=list)
    extra_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON変換用の辞書表現を返す。"""
        payload: dict[str, Any] = {
            "instruction": self.instruction,
            "project_name": self.project_name,
        }
        if self.git_status_summary:
            payload["git_status_summary"] = self.git_status_summary
        if self.git_diff:
            payload["git_diff"] = self.git_diff
        if self.error_output:
            payload["error_output"] = self.error_output
        if self.test_output:
            payload["test_output"] = self.test_output
        if self.lint_output:
            payload["lint_output"] = self.lint_output
        if self.context_files:
            payload["context_files"] = [f.to_dict() for f in self.context_files]
        if self.extra_notes:
            payload["extra_notes"] = self.extra_notes
        payload["response_json_schema"] = RESPONSE_JSON_SCHEMA
        return payload

    def to_json_string(self, *, indent: int = 2) -> str:
        """整形済みJSON文字列を返す。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass(slots=True)
class JsonFilePatch:
    """レスポンスに含まれる1ファイル分のパッチ情報。"""

    path: str
    content: str
    action: str = "update"


@dataclass(slots=True)
class JsonParsedResponse:
    """AIからのJSONレスポンスをパースした結果。"""

    summary: str = ""
    files: list[JsonFilePatch] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    todos: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    task_complete: bool = False

    @property
    def file_patches(self) -> dict[str, str]:
        """ファイルパス→内容の辞書を返す(Patch Engineへそのまま渡せる形式)。"""
        return {f.path: f.content for f in self.files}


class JsonResponseParseError(ValueError):
    """AIからのレスポンスが期待するJSONスキーマに従っていない場合に送出される。"""


class JsonResponseParser:
    """AIからのJSON文字列をパースし `JsonParsedResponse` を構築するクラス。"""

    def parse(self, raw_text: str) -> JsonParsedResponse:
        """AI回答の生テキストからJSON部分を抽出しパースする。

        AIが ```json ... ``` のようにコードフェンスで囲んでしまうケースにも
        対応するため、まず素直に `json.loads` を試み、失敗したらコードフェンス
        除去を試みる。
        """
        data = self._extract_json_object(raw_text)
        return self._build_from_dict(data)

    def _extract_json_object(self, raw_text: str) -> dict[str, Any]:
        """テキストからJSONオブジェクトを抽出する。"""
        candidate = raw_text.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # ```json ... ``` や ``` ... ``` で囲まれている場合を試す。
        if "```" in candidate:
            parts = candidate.split("```")
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[len("json") :].strip()
                if not cleaned:
                    continue
                try:
                    return json.loads(cleaned)
                except json.JSONDecodeError:
                    continue

        # 先頭の '{' から末尾の '}' までを取り出して再試行する(前後に説明文がある場合)。
        first_brace = candidate.find("{")
        last_brace = candidate.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(candidate[first_brace : last_brace + 1])
            except json.JSONDecodeError as exc:
                raise JsonResponseParseError(
                    "AIの回答からJSONを抽出できませんでした。有効なJSON形式で回答するよう再度依頼してください。"
                ) from exc

        raise JsonResponseParseError(
            "AIの回答からJSONを抽出できませんでした。有効なJSON形式で回答するよう再度依頼してください。"
        )

    def _build_from_dict(self, data: dict[str, Any]) -> JsonParsedResponse:
        """辞書から `JsonParsedResponse` を構築する(欠損フィールドは寛容に扱う)。"""
        files = [
            JsonFilePatch(
                path=str(item.get("path", "")),
                content=str(item.get("content", "")),
                action=str(item.get("action", "update")),
            )
            for item in data.get("files", [])
            if item.get("path")
        ]
        return JsonParsedResponse(
            summary=str(data.get("summary", "")),
            files=files,
            commands=[str(c) for c in data.get("commands", [])],
            todos=[str(t) for t in data.get("todos", [])],
            notes=[str(n) for n in data.get("notes", [])],
            task_complete=bool(data.get("task_complete", False)),
        )
