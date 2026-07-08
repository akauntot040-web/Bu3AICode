"""Google AI Studio(Gemini API)クライアント。

PromptAgentは「AI APIを使わない」ことを基本方針とするが、利用者が明示的に
`ai_backend.provider: google_ai_studio` を設定した場合に限り、Google AI Studio
(Generative Language API)を直接呼び出せるようにする。他のAI API(OpenAI /
Anthropic / Gemini以外)やローカルLLMは意図的にサポートしない。

外部依存を増やさないため、公式SDKではなく標準ライブラリの `urllib` で
REST APIを直接呼び出す。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

_API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiAPIError(RuntimeError):
    """Gemini API呼び出しが失敗した場合に送出される。"""


class GeminiAPIKeyMissingError(GeminiAPIError):
    """APIキーが設定されていない場合に送出される。"""


@dataclass(slots=True)
class GeminiResponse:
    """Gemini APIからの応答。"""

    text: str
    raw: dict


class GeminiClient:
    """Google AI Studio(Gemini API)の `generateContent` エンドポイントを呼び出すクライアント。"""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        *,
        timeout_seconds: float = 120.0,
        temperature: float = 0.2,
    ) -> None:
        if not api_key:
            raise GeminiAPIKeyMissingError(
                "Google AI StudioのAPIキーが設定されていません。"
                "config.yamlのai_backend.api_keyか、環境変数(既定: GOOGLE_API_KEY)を設定してください。"
            )
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature

    def generate(self, prompt_text: str, *, system_instruction: str | None = None) -> GeminiResponse:
        """プロンプト文字列を送信し、テキスト応答を取得する。"""
        url = f"{_API_BASE_URL}/{self._model}:generateContent?key={self._api_key}"

        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
            "generationConfig": {"temperature": self._temperature},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise GeminiAPIError(f"Gemini APIがエラーを返しました(HTTP {exc.code}): {error_body}") from exc
        except urllib.error.URLError as exc:
            raise GeminiAPIError(f"Gemini APIへの接続に失敗しました: {exc.reason}") from exc

        data = json.loads(raw_body)
        text = self._extract_text(data)
        return GeminiResponse(text=text, raw=data)

    @staticmethod
    def _extract_text(data: dict) -> str:
        """Gemini APIのレスポンスからテキスト部分を抽出する。"""
        try:
            candidates = data["candidates"]
            parts = candidates[0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiAPIError(f"Gemini APIのレスポンス形式が想定と異なります: {data}") from exc
