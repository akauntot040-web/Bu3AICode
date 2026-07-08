"""PythonJediBackendの単体テスト。"""

from __future__ import annotations

from pathlib import Path

from promptagent.lsp.language_service import LanguageServiceRegistry


def test_list_symbols_detects_function_and_class(tmp_path: Path) -> None:
    source = (
        "def greet(name):\n"
        "    return f'hello {name}'\n\n"
        "class Greeter:\n"
        "    def run(self):\n"
        "        pass\n"
    )
    file_path = tmp_path / "sample.py"
    file_path.write_text(source, encoding="utf-8")

    registry = LanguageServiceRegistry(tmp_path)
    backend = registry.get_backend(file_path)
    assert backend is not None

    symbols = backend.list_symbols(file_path)
    names = {s.name for s in symbols}
    assert "greet" in names
    assert "Greeter" in names


def test_goto_definition_finds_function_definition(tmp_path: Path) -> None:
    source = "def greet():\n    return 1\n\nresult = greet()\n"
    file_path = tmp_path / "sample.py"
    file_path.write_text(source, encoding="utf-8")

    registry = LanguageServiceRegistry(tmp_path)
    backend = registry.get_backend(file_path)
    assert backend is not None

    # 4行目の "greet" 呼び出し部分から定義へジャンプ
    locations = backend.goto_definition(file_path, line=4, column=11)
    assert len(locations) == 1
    assert locations[0].line == 1


def test_unsupported_extension_returns_none_backend(tmp_path: Path) -> None:
    registry = LanguageServiceRegistry(tmp_path)
    backend = registry.get_backend(tmp_path / "sample.rs")
    assert backend is None
