"""再利用可能なRich UIコンポーネント群。

ステータスバー、ブレッドクラム、ツリー表示、Diffビューア、Markdown表示、
テーブル表示など、CLI全体で使い回すビジュアル部品を提供する。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from promptagent.config import ThemeConfig


@dataclass(slots=True)
class StatusBarInfo:
    """ステータスバーに表示する情報。"""

    project_name: str
    branch: str
    language_summary: str
    context_tokens: int
    dirty: bool = False


def render_status_bar(theme: ThemeConfig, info: StatusBarInfo) -> RenderableType:
    """画面下部に表示するステータスバーを構築する。"""
    dirty_mark = "●" if info.dirty else "○"
    text = Text()
    text.append(f" {info.project_name} ", style=Style(color=theme.background, bgcolor=theme.accent, bold=True))
    text.append(f" {dirty_mark} {info.branch} ", style=Style(color=theme.text))
    text.append(f" | {info.language_summary} ", style=Style(color=theme.muted))
    text.append(f" | ctx:{info.context_tokens} tok ", style=Style(color=theme.muted))
    return Panel(text, style=Style(bgcolor=theme.surface), padding=(0, 1))


def render_breadcrumb(theme: ThemeConfig, parts: list[str]) -> RenderableType:
    """パンくずリストを描画する。"""
    text = Text()
    for index, part in enumerate(parts):
        if index > 0:
            text.append(" › ", style=Style(color=theme.muted))
        style = Style(color=theme.accent, bold=True) if index == len(parts) - 1 else Style(color=theme.text)
        text.append(part, style=style)
    return text


def render_file_tree(theme: ThemeConfig, root: Path, files: list[Path]) -> Tree:
    """指定ファイル群からディレクトリツリーを構築する。"""
    tree = Tree(f"[bold]{root.name}[/bold]", guide_style=Style(color=theme.muted))
    nodes: dict[Path, Tree] = {root: tree}

    for file_path in sorted(files):
        try:
            relative = file_path.relative_to(root)
        except ValueError:
            continue
        current = root
        current_node = tree
        for part in relative.parts[:-1]:
            current = current / part
            if current not in nodes:
                nodes[current] = current_node.add(f"[cyan]{part}/[/cyan]")
            current_node = nodes[current]
        current_node.add(relative.parts[-1])

    return tree


def render_markdown(text: str) -> Markdown:
    """Markdown文字列をRich描画可能オブジェクトへ変換する。"""
    return Markdown(text, code_theme="monokai")


def render_code(code: str, language: str, *, line_numbers: bool = True) -> Syntax:
    """シンタックスハイライト付きコードブロックを描画する。"""
    return Syntax(code, language or "text", theme="monokai", line_numbers=line_numbers, word_wrap=True)


def render_diff(theme: ThemeConfig, old_text: str, new_text: str, filename: str) -> RenderableType:
    """2つのテキストのユニファイド差分をカラー表示する。"""
    diff_lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )
    text = Text()
    for line in diff_lines:
        if line.startswith("+") and not line.startswith("+++"):
            text.append(line, style=Style(color=theme.success))
        elif line.startswith("-") and not line.startswith("---"):
            text.append(line, style=Style(color=theme.error))
        elif line.startswith("@@"):
            text.append(line, style=Style(color=theme.accent, bold=True))
        else:
            text.append(line, style=Style(color=theme.muted))
    return Panel(text, title=f"diff: {filename}", border_style=Style(color=theme.accent))


def render_table(theme: ThemeConfig, title: str, columns: list[str], rows: list[list[str]]) -> Table:
    """汎用テーブルを構築する。"""
    table = Table(title=title, border_style=Style(color=theme.muted), header_style=Style(color=theme.accent, bold=True))
    for column in columns:
        table.add_column(column)
    for row in rows:
        table.add_row(*row)
    return table


def render_shortcut_help(theme: ThemeConfig, keybindings: dict[str, str]) -> RenderableType:
    """ショートカット一覧パネルを構築する。"""
    table = Table.grid(padding=(0, 2))
    table.add_column(justify="right", style=Style(color=theme.accent, bold=True))
    table.add_column(justify="left", style=Style(color=theme.text))
    for action, key in keybindings.items():
        table.add_row(key, action)
    return Panel(table, title="ショートカット", border_style=Style(color=theme.muted))


def print_panel(console: Console, theme: ThemeConfig, title: str, body: RenderableType) -> None:
    """タイトル付きパネルを出力する共通ヘルパー。"""
    console.print(Panel(body, title=title, border_style=Style(color=theme.accent), padding=(1, 2)))
