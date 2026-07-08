"""Command Palette。

コマンド一覧・最近使ったファイル・最近使ったプロジェクトなどを対象に
あいまい検索を行い、Rich上で候補一覧を表示して選択を受け付ける。
Textual未使用でも `prompt_toolkit` の入力とRichの表示だけで動作する
軽量な実装。
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt
from rich.style import Style
from rich.table import Table

from promptagent.config import ThemeConfig
from promptagent.utils.fuzzy import fuzzy_find, highlight_match


@dataclass(slots=True)
class PaletteItem:
    """コマンドパレットに表示する1項目。"""

    label: str
    description: str = ""
    payload: str = ""


class CommandPalette:
    """あいまい検索付きの選択UIを提供するクラス。"""

    def __init__(self, console: Console, theme: ThemeConfig) -> None:
        self._console = console
        self._theme = theme

    def select(self, items: list[PaletteItem], query: str = "") -> PaletteItem | None:
        """候補一覧から1件を選択させる。空リストならNoneを返す。"""
        if not items:
            self._console.print("[dim]候補がありません。[/dim]")
            return None

        labels = [item.label for item in items]
        matches = fuzzy_find(query, labels, limit=15) if query else [
            type("M", (), {"candidate": label, "matched_indices": []})() for label in labels[:15]
        ]

        if not matches:
            self._console.print(f"[yellow]'{query}' に一致する候補がありません。[/yellow]")
            return None

        label_to_item = {item.label: item for item in items}

        table = Table(title="Command Palette", border_style=Style(color=self._theme.accent))
        table.add_column("#", justify="right", style=Style(color=self._theme.muted))
        table.add_column("項目", style=Style(color=self._theme.text))
        table.add_column("説明", style=Style(color=self._theme.muted))

        for index, match in enumerate(matches, start=1):
            item = label_to_item[match.candidate]
            highlighted = highlight_match(match) if query else match.candidate
            table.add_row(str(index), highlighted, item.description)

        self._console.print(Panel(table, border_style=Style(color=self._theme.accent)))

        choice = IntPrompt.ask(
            "番号を選択してください(0でキャンセル)", default=0, show_default=False
        )
        if choice <= 0 or choice > len(matches):
            return None
        selected_label = matches[choice - 1].candidate
        return label_to_item[selected_label]
