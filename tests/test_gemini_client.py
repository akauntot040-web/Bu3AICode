"""GeminiClientの単体テスト(実ネットワーク呼び出しはモックする)。"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from promptagent.ai_backend.gemini_client import (
    GeminiAPIError,
    GeminiAPIKeyMissingError,
    GeminiClient,
)


def test_missing_api_key_raises() -> None:
    with pytest.raises(GeminiAPIKeyMissingError):
        GeminiClient(api_key="")


def _make_urlopen_mock(response_body: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(response_body).encode("utf-8")
    mock_response.__enter__ = lambda self: mock_response
    mock_response.__exit__ = lambda self, *args: None
    return mock_response


def test_generate_extracts_text_from_response() -> None:
    client = GeminiClient(api_key="dummy-key")
    fake_response = {
        "candidates": [{"content": {"parts": [{"text": '{"summary": "ok"}'}]}}]
    }
    with patch("urllib.request.urlopen", return_value=_make_urlopen_mock(fake_response)):
        result = client.generate("テストプロンプト")
    assert result.text == '{"summary": "ok"}'


def test_generate_raises_on_http_error() -> None:
    client = GeminiClient(api_key="dummy-key")
    http_error = urllib.error.HTTPError(
        url="https://example.com", code=400, msg="Bad Request", hdrs=None, fp=None
    )
    http_error.read = lambda: b'{"error": "invalid request"}'
    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(GeminiAPIError):
            client.generate("テストプロンプト")


def test_generate_raises_on_malformed_response() -> None:
    client = GeminiClient(api_key="dummy-key")
    fake_response = {"unexpected": "shape"}
    with patch("urllib.request.urlopen", return_value=_make_urlopen_mock(fake_response)):
        with pytest.raises(GeminiAPIError):
            client.generate("テストプロンプト")
