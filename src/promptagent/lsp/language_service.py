"""Language Server風の解析機能。

フル機能のLSPクライアントを実装する代わりに、Pythonについては `jedi` を
用いて定義ジャンプ・参照検索・シンボル解析を提供する。他言語は将来的に
言語ごとのバックエンドを追加できるよう、`LanguageBackend` プロトコルとして
抽象化してある。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class SourceLocation:
    """ソースコード上の位置情報。"""

    file_path: Path
    line: int
    column: int
    context_line: str = ""


@dataclass(slots=True)
class SymbolInfo:
    """シンボル(関数・クラス・変数等)の情報。"""

    name: str
    kind: str
    location: SourceLocation
    signature: str = ""


class LanguageBackend(Protocol):
    """言語ごとの解析バックエンドが実装すべきインタフェース。"""

    def goto_definition(self, file_path: Path, line: int, column: int) -> list[SourceLocation]:
        """指定位置のシンボルの定義位置一覧を返す。"""
        ...

    def find_references(self, file_path: Path, line: int, column: int) -> list[SourceLocation]:
        """指定位置のシンボルの参照位置一覧を返す。"""
        ...

    def list_symbols(self, file_path: Path) -> list[SymbolInfo]:
        """ファイル内のトップレベルシンボル一覧を返す。"""
        ...


class PythonJediBackend:
    """`jedi` を利用したPython向け解析バックエンド。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def _make_script(self, file_path: Path):  # noqa: ANN202
        """jedi.Scriptインスタンスを生成する(内部利用)。"""
        import jedi

        source = file_path.read_text(encoding="utf-8", errors="replace")
        project = jedi.Project(str(self._project_root))
        return jedi.Script(code=source, path=str(file_path), project=project)

    def goto_definition(self, file_path: Path, line: int, column: int) -> list[SourceLocation]:
        """カーソル位置のシンボルの定義位置を取得する。"""
        try:
            script = self._make_script(file_path)
            definitions = script.goto(line=line, column=column, follow_imports=True)
        except Exception:
            return []
        return [self._to_location(d) for d in definitions if d.module_path]

    def find_references(self, file_path: Path, line: int, column: int) -> list[SourceLocation]:
        """カーソル位置のシンボルの参照箇所を取得する。"""
        try:
            script = self._make_script(file_path)
            references = script.get_references(line=line, column=column)
        except Exception:
            return []
        return [self._to_location(r) for r in references if r.module_path]

    def list_symbols(self, file_path: Path) -> list[SymbolInfo]:
        """ファイル内の関数・クラス定義などのシンボル一覧を取得する。"""
        try:
            script = self._make_script(file_path)
            names = script.get_names(all_scopes=False, definitions=True, references=False)
        except Exception:
            return []

        symbols = []
        for name in names:
            symbols.append(
                SymbolInfo(
                    name=name.name,
                    kind=name.type,
                    location=SourceLocation(
                        file_path=Path(name.module_path or file_path),
                        line=name.line or 0,
                        column=name.column or 0,
                    ),
                    signature=self._safe_signature(name),
                )
            )
        return symbols

    @staticmethod
    def _safe_signature(name) -> str:  # noqa: ANN001
        """jediのSignature取得を安全に行う。"""
        try:
            signatures = name.get_signatures()
            return signatures[0].to_string() if signatures else ""
        except Exception:
            return ""

    @staticmethod
    def _to_location(definition) -> SourceLocation:  # noqa: ANN001
        """jediのDefinitionオブジェクトを `SourceLocation` へ変換する。"""
        try:
            context_line = definition.get_line_code().strip()
        except Exception:
            context_line = ""
        return SourceLocation(
            file_path=Path(definition.module_path),
            line=definition.line or 0,
            column=definition.column or 0,
            context_line=context_line,
        )


class LanguageServiceRegistry:
    """拡張子ごとに適切な `LanguageBackend` を提供するレジストリ。"""

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root
        self._backends: dict[str, LanguageBackend] = {}

    def get_backend(self, file_path: Path) -> LanguageBackend | None:
        """ファイル拡張子に対応するバックエンドを返す(未対応言語はNone)。"""
        suffix = file_path.suffix.lower()
        if suffix in (".py", ".pyi"):
            if "python" not in self._backends:
                self._backends["python"] = PythonJediBackend(self._project_root)
            return self._backends["python"]
        return None
