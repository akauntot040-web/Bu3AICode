"""Textualによるフルスクリーン対話UI。

行指向CLI(`cli.py`)が提供する全機能を、サイドバー(ファイルツリー)+
メインログパネル+コマンド入力+ステータスバーという分割レイアウトの
フルスクリーンTUIとして提供する。既存の `PromptAgentApp` のロジックを
再利用し、UI層だけをTextualに置き換える。

`/prompt` はHuman Loopが `input()` を使う都合上、行指向CLIとは異なる
モーダルダイアログ(`HumanLoopModal`)で実現する。プロンプトのコピーと
AI回答の貼り付けをどちらも画面内のテキスト領域で行える。

`config.yaml` の `theme` セクションはCSS変数として動的に反映され、
パッチ適用(AfterPatchフック)後はサイドバーのファイルツリーが自動で
再構築される。
"""

from __future__ import annotations

import pyperclip
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, RichLog, Static, TextArea, Tree

from typing import TYPE_CHECKING

from promptagent.hooks.hook_manager import HookEvent

if TYPE_CHECKING:
    from promptagent.cli import PromptAgentApp
    from promptagent.config import ThemeConfig


def build_theme_css(theme: "ThemeConfig") -> str:
    """`config.yaml` のテーマ設定からTextual用CSS文字列を動的に生成する。"""
    return f"""
    Screen {{
        background: {theme.background};
        color: {theme.text};
    }}
    #sidebar {{
        width: 32%;
        border-right: solid {theme.surface};
        background: {theme.surface};
    }}
    #main {{
        width: 68%;
    }}
    #log {{
        background: {theme.background};
        color: {theme.text};
    }}
    #command-input {{
        dock: bottom;
        border: solid {theme.accent};
    }}
    Tree {{
        background: {theme.surface};
        color: {theme.text};
    }}
    Header {{
        background: {theme.surface};
        color: {theme.accent};
    }}
    Footer {{
        background: {theme.surface};
        color: {theme.muted};
    }}
    """


class _CapturingConsole:
    """RichLogへ出力をリダイレクトするための `Console.print` 差し替え先。"""

    def __init__(self, log_widget: RichLog) -> None:
        self._log_widget = log_widget

    def print(self, *args: object, **_kwargs: object) -> None:
        """Console.print相当の呼び出しをRichLogへ転送する。"""
        for arg in args:
            self._log_widget.write(arg if not isinstance(arg, str) else Text.from_markup(arg))


class HumanLoopModal(ModalScreen[str | None]):
    """AIへのプロンプト提示とAI回答の貼り付けを1画面で行うモーダル。

    画面を閉じると、貼り付けられた回答文字列(空文字含む)を返す。
    キャンセル時はNoneを返す。
    """

    CSS = """
    HumanLoopModal {
        align: center middle;
    }
    #modal-box {
        width: 90%;
        height: 90%;
        background: #101014;
        border: solid #7C5CFF;
        padding: 1 2;
    }
    #prompt-preview {
        height: 40%;
        border: solid #26262E;
        background: #0B0B0F;
        color: #E6E6EA;
    }
    #response-area {
        height: 40%;
        border: solid #26262E;
    }
    #modal-buttons {
        height: auto;
        align: right middle;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "キャンセル")]

    def __init__(self, prompt_text: str) -> None:
        super().__init__()
        self._prompt_text = prompt_text
        self._copy_succeeded = True

    def compose(self) -> ComposeResult:
        """モーダルのレイアウトを構築する。"""
        with Vertical(id="modal-box"):
            yield Label(f"[bold]AIへ送るプロンプト[/bold] ({len(self._prompt_text):,}文字)")
            with VerticalScroll(id="prompt-preview"):
                yield Static(self._prompt_text, markup=False)
            yield Label("[dim]コピー後、AIの回答をここに貼り付けてください[/dim]")
            yield TextArea(id="response-area")
            with Horizontal(id="modal-buttons"):
                yield Button("クリップボードへ再コピー", id="copy-again")
                yield Button("キャンセル", id="cancel", variant="default")
                yield Button("送信して解析", id="submit", variant="primary")

    def on_mount(self) -> None:
        """マウント時にクリップボードへプロンプトをコピーする。"""
        try:
            pyperclip.copy(self._prompt_text)
        except pyperclip.PyperclipException:
            self._copy_succeeded = False

    @on(Button.Pressed, "#copy-again")
    def _on_copy_again(self) -> None:
        """再コピー要求を処理する。"""
        try:
            pyperclip.copy(self._prompt_text)
            self.notify("クリップボードへコピーしました", timeout=2)
        except pyperclip.PyperclipException:
            self.notify("クリップボードへのコピーに失敗しました", severity="error", timeout=3)

    @on(Button.Pressed, "#cancel")
    def _on_cancel(self) -> None:
        """キャンセルボタン押下時の処理。"""
        self.dismiss(None)

    @on(Button.Pressed, "#submit")
    def _on_submit(self) -> None:
        """送信ボタン押下時、貼り付けられた回答を結果として返す。"""
        response_text = self.query_one("#response-area", TextArea).text
        self.dismiss(response_text)

    def action_cancel(self) -> None:
        """Escキーでのキャンセル。"""
        self.dismiss(None)


class CommandPaletteModal(ModalScreen[str | None]):
    """コマンド/ファイルのあいまい検索を行うオーバーレイモーダル。"""

    CSS = """
    CommandPaletteModal {
        align: center top;
    }
    #palette-box {
        width: 70%;
        margin-top: 3;
        background: #101014;
        border: solid #7C5CFF;
        padding: 1 2;
        height: auto;
        max-height: 80%;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "キャンセル")]

    def __init__(self, candidates: list[str]) -> None:
        super().__init__()
        self._candidates = candidates

    def compose(self) -> ComposeResult:
        """パレットのレイアウトを構築する。"""
        with Vertical(id="palette-box"):
            yield Input(placeholder="検索...", id="palette-query")
            yield ListView(id="palette-results")

    def on_mount(self) -> None:
        """初期候補一覧を表示する。"""
        self._refresh_results("")
        self.query_one("#palette-query", Input).focus()

    def _refresh_results(self, query: str) -> None:
        """あいまい検索を実行し結果一覧を更新する。"""
        from promptagent.utils.fuzzy import fuzzy_find

        list_view = self.query_one("#palette-results", ListView)
        list_view.clear()
        matches = fuzzy_find(query, self._candidates, limit=15)
        for match in matches:
            list_view.append(ListItem(Label(match.candidate)))

    @on(Input.Changed, "#palette-query")
    def _on_query_changed(self, event: Input.Changed) -> None:
        """入力の変化に応じて候補を再検索する。"""
        self._refresh_results(event.value)

    @on(ListView.Selected, "#palette-results")
    def _on_selected(self, event: ListView.Selected) -> None:
        """候補選択時、その文字列を結果として返す。"""
        label_widget = event.item.query_one(Label)
        self.dismiss(str(label_widget.renderable))

    def action_cancel(self) -> None:
        """Escキーでのキャンセル。"""
        self.dismiss(None)


class PromptAgentTUI(App[None]):
    """PromptAgentのフルスクリーンTUIアプリケーション。"""

    BINDINGS = [
        Binding("ctrl+l", "clear_log", "クリア"),
        Binding("ctrl+q", "quit", "終了"),
        Binding("ctrl+p", "open_palette", "コマンドパレット"),
        Binding("ctrl+f", "focus_input", "コマンド入力"),
    ]

    def __init__(self, cli_app: "PromptAgentApp") -> None:
        # config.yamlのテーマ設定をCSSへ動的反映するため、コンストラクタ内で
        # インスタンス属性としてCSSを設定する(クラス変数のCSSより先に評価される)。
        self.CSS = build_theme_css(cli_app.config.theme)
        super().__init__()
        self._cli_app = cli_app
        self.title = f"PromptAgent — {cli_app.project_root.name}"
        self._register_tree_refresh_hook()

    def _register_tree_refresh_hook(self) -> None:
        """ファイル更新後にサイドバーのツリーを自動再構築するフックを登録する。"""

        def _on_after_patch(_context: dict) -> None:
            # フックはworker(同一イベントループ上のタスク)から発火されるため、
            # 別スレッド専用のcall_from_threadは使わず直接呼び出す。
            self._refresh_tree_and_analysis()

        self._cli_app.hooks.register(HookEvent.AFTER_PATCH, _on_after_patch)

    def _refresh_tree_and_analysis(self) -> None:
        """プロジェクト解析結果を再取得し、ファイルツリーを再構築する。"""
        assert self._cli_app.analysis is not None
        self._cli_app.analysis = self._cli_app.analyzer.analyze(self._cli_app.project_root)
        self._cli_app.cache.set_project_analysis(
            str(self._cli_app.project_root), self._cli_app.analysis.to_dict()
        )
        self._populate_tree()

    def compose(self) -> ComposeResult:
        """レイアウトを構築する。"""
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Tree("Project", id="file-tree")
            with Vertical(id="main"):
                yield RichLog(id="log", markup=True, wrap=True, highlight=True)
        yield Input(placeholder="コマンドを入力... (例: /prompt バグを修正して)", id="command-input")
        yield Footer()

    def on_mount(self) -> None:
        """マウント時にファイルツリーを構築し、ようこそメッセージを表示する。"""
        self._populate_tree()
        log_widget = self.query_one("#log", RichLog)
        log_widget.write(
            "[bold]PromptAgent TUIへようこそ[/bold]\n"
            "下部の入力欄に /prompt などのコマンドを入力してください。\n"
            "Ctrl+Pでコマンドパレット、Ctrl+Qで終了、Ctrl+Lでログクリア。"
        )
        self.query_one("#command-input", Input).focus()

    def _populate_tree(self) -> None:
        """サイドバーへプロジェクトのファイルツリーを構築する。"""
        tree_widget = self.query_one("#file-tree", Tree)
        tree_widget.clear()
        tree_widget.root.label = self._cli_app.project_root.name
        analysis = self._cli_app.analysis
        if analysis is None:
            return

        nodes = {self._cli_app.project_root: tree_widget.root}
        for file_info in sorted(analysis.files, key=lambda f: str(f.path)):
            try:
                relative = file_info.path.relative_to(self._cli_app.project_root)
            except ValueError:
                continue
            current_path = self._cli_app.project_root
            current_node = tree_widget.root
            for part in relative.parts[:-1]:
                current_path = current_path / part
                if current_path not in nodes:
                    nodes[current_path] = current_node.add(part)
                current_node = nodes[current_path]
            current_node.add_leaf(relative.parts[-1])
        tree_widget.root.expand()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """コマンド入力欄でEnterが押された際の処理。"""
        command_text = event.value.strip()
        event.input.value = ""
        if not command_text:
            return

        log_widget = self.query_one("#log", RichLog)
        log_widget.write(f"[bold #7C5CFF]promptagent>[/bold #7C5CFF] {command_text}")

        command, _, rest = command_text.partition(" ")
        if command == "/prompt":
            self.run_worker(self._handle_prompt_command(rest.strip(), log_widget), exclusive=True)
            return
        if command == "/tui":
            log_widget.write("[dim]既にTUI内です。[/dim]")
            return

        original_console_print = self._cli_app.console.print
        self._cli_app.console.print = _CapturingConsole(log_widget).print  # type: ignore[method-assign]
        try:
            should_continue = self._cli_app._dispatch(command_text)
        except Exception as exc:  # noqa: BLE001
            log_widget.write(f"[red]エラー: {exc}[/red]")
            should_continue = True
        finally:
            self._cli_app.console.print = original_console_print  # type: ignore[method-assign]

        if not should_continue:
            self.exit()

    async def _handle_prompt_command(self, instruction: str, log_widget: RichLog) -> None:
        """`/prompt` をモーダルによるHuman Loopとして処理する。"""
        if not instruction:
            log_widget.write("[yellow]指示文を入力してください: /prompt <指示文>[/yellow]")
            return

        _request, prompt_text = self._cli_app.build_prompt_request(instruction)
        response_text = await self.push_screen_wait(HumanLoopModal(prompt_text))

        if response_text is None:
            log_widget.write("[dim]キャンセルされました。[/dim]")
            return

        original_console_print = self._cli_app.console.print
        self._cli_app.console.print = _CapturingConsole(log_widget).print  # type: ignore[method-assign]
        try:
            cycle_result = self._cli_app.process_ai_response(prompt_text, response_text, _request)
            if cycle_result is None:
                log_widget.write("[dim]回答が空のため処理をスキップします。[/dim]")
            else:
                self._cli_app._report_cycle_result(cycle_result)
        finally:
            self._cli_app.console.print = original_console_print  # type: ignore[method-assign]

    async def action_open_palette(self) -> None:
        """Command Paletteモーダルを開き、選択結果を入力欄へ反映する。"""
        analysis = self._cli_app.analysis
        candidates: list[str] = []
        if analysis is not None:
            candidates = [str(f.path.relative_to(self._cli_app.project_root)) for f in analysis.files]

        selected = await self.push_screen_wait(CommandPaletteModal(candidates))
        if selected:
            input_widget = self.query_one("#command-input", Input)
            input_widget.value = f"/find {selected}"
            input_widget.focus()

    def action_clear_log(self) -> None:
        """ログをクリアする。"""
        self.query_one("#log", RichLog).clear()

    def action_focus_input(self) -> None:
        """コマンド入力欄へフォーカスを移す。"""
        self.query_one("#command-input", Input).focus()

