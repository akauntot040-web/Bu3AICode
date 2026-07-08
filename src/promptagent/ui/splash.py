"""起動時スプラッシュ画面。

美しいASCIIロゴをフェードインさせ、続けてローディングアニメーションを
表示する。黒基調・余白を活かしたミニマルデザイン。
"""

from __future__ import annotations

import time

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from promptagent.config import ThemeConfig

_LOGO = r"""
██████╗ ██████╗  ██████╗ ███╗   ███╗██████╗ ████████╗ █████╗  ██████╗ ███████╗███╗   ██╗████████╗
██╔══██╗██╔══██╗██╔═══██╗████╗ ████║██╔══██╗╚══██╔══╝██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝
██████╔╝██████╔╝██║   ██║██╔████╔██║██████╔╝   ██║   ███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║
██╔═══╝ ██╔══██╗██║   ██║██║╚██╔╝██║██╔═══╝    ██║   ██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║
██║     ██║  ██║╚██████╔╝██║ ╚═╝ ██║██║        ██║   ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║
╚═╝     ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝        ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝
"""

_TAGLINE = "AI APIを使わない、人間仲介型の開発支援CLI"


def _fade_style(theme: ThemeConfig, ratio: float) -> Style:
    """0.0(暗)〜1.0(明)の比率でアクセントカラーへフェードするスタイルを返す。"""
    ratio = max(0.0, min(1.0, ratio))

    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        value = value.lstrip("#")
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    bg = _hex_to_rgb(theme.background)
    fg = _hex_to_rgb(theme.accent)
    mixed = tuple(int(bg[i] + (fg[i] - bg[i]) * ratio) for i in range(3))
    return Style(color=f"rgb({mixed[0]},{mixed[1]},{mixed[2]})")


def render_splash(console: Console, theme: ThemeConfig, *, animate: bool = True) -> None:
    """スプラッシュ画面をフェードインで描画する。"""
    steps = 12 if animate else 1
    with Live(console=console, refresh_per_second=30, transient=True) as live:
        for step in range(1, steps + 1):
            ratio = step / steps
            logo_text = Text(_LOGO, style=_fade_style(theme, ratio), justify="center")
            tagline = Text(_TAGLINE, style=Style(color=theme.muted, italic=True), justify="center")
            body = Group(Align.center(logo_text), Text(""), Align.center(tagline))
            panel = Panel(
                body,
                border_style=Style(color=theme.accent) if ratio > 0.6 else Style(color=theme.surface),
                padding=(2, 4),
            )
            live.update(Align.center(panel, vertical="middle"))
            if animate:
                time.sleep(0.03)
        if animate:
            time.sleep(0.25)


def render_loading(console: Console, theme: ThemeConfig, message: str, *, duration: float = 0.8) -> None:
    """短いローディングスピナーを表示する（ステータス更新演出用）。"""
    from rich.spinner import Spinner

    with Live(console=console, refresh_per_second=20, transient=True) as live:
        spinner = Spinner("dots", text=Text(f" {message}", style=Style(color=theme.text)))
        start = time.monotonic()
        while time.monotonic() - start < duration:
            live.update(Align.left(spinner))
            time.sleep(0.05)
