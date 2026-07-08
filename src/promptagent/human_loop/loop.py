"""Human Loop。

生成したプロンプトをクリップボードへコピーし、ユーザーがWeb版AIチャットへ
貼り付けて得た回答を、再びこのCLIへ貼り戻すまでの「人間仲介」フローを
管理する。AIモデル自体は一切呼び出さない。
"""

from __future__ import annotations

from dataclasses import dataclass

import pyperclip
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.style import Style

from promptagent.config import ThemeConfig

_END_MARKER = "END"


@dataclass(slots=True)
class HumanLoopResult:
    """Human Loop 1往復分の結果。"""

    prompt_text: str
    response_text: str
    copy_succeeded: bool


class HumanLoop:
    """プロンプトのコピー提示と、AI回答の貼り付け受付を担当するクラス。"""

    def __init__(self, console: Console, theme: ThemeConfig) -> None:
        self._console = console
        self._theme = theme

    def deliver_prompt(self, prompt_text: str) -> bool:
        """プロンプトをクリップボードへコピーし、ユーザーへ貼り付けを促す。"""
        copy_succeeded = True
        try:
            pyperclip.copy(prompt_text)
        except pyperclip.PyperclipException:
            copy_succeeded = False

        char_count = len(prompt_text)
        message = (
            "次の文章をAIへ貼り付けてください。\n\n"
            f"[bold]文字数: {char_count:,}文字[/bold]\n"
        )
        if copy_succeeded:
            message += "\n[green]✓ クリップボードへコピー済みです。[/green]"
        else:
            message += (
                "\n[yellow]⚠ クリップボードへのコピーに失敗しました。"
                "下記のプロンプトを手動でコピーしてください。[/yellow]"
            )

        self._console.print(
            Panel(message, title="Human Loop: プロンプト送信", border_style=Style(color=self._theme.accent))
        )
        if not copy_succeeded:
            self._console.print(
                Panel(prompt_text, title="プロンプト全文", border_style=Style(color=self._theme.muted))
            )

        Prompt.ask(
            "[dim]コピー完了後、Enterキーで続行してください[/dim]",
            default="",
            show_default=False,
        )
        return copy_succeeded

    def receive_response(self) -> str:
        """AIの回答を複数行入力として受け付ける。`END` 単独行で入力終了。"""
        self._console.print(
            Panel(
                "AIの回答を貼り付けてください。\n"
                f"入力が終わったら単独行で [bold]{_END_MARKER}[/bold] と入力してください。",
                title="Human Loop: AI回答待ち",
                border_style=Style(color=self._theme.accent),
            )
        )

        lines: list[str] = []
        while True:
            try:
                line = input()
            except EOFError:
                break
            if line.strip() == _END_MARKER:
                break
            lines.append(line)

        response_text = "\n".join(lines)
        self._console.print(
            f"[dim]回答を受信しました({len(response_text):,}文字)。解析を開始します...[/dim]"
        )
        return response_text

    def run_round_trip(self, prompt_text: str) -> HumanLoopResult:
        """プロンプト提示から回答受信までの一往復を実行する。"""
        copy_succeeded = self.deliver_prompt(prompt_text)
        response_text = self.receive_response()
        return HumanLoopResult(
            prompt_text=prompt_text, response_text=response_text, copy_succeeded=copy_succeeded
        )
