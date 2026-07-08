"""PromptAgent CLIエントリポイント。

起動処理・スプラッシュ画面・プロジェクト解析・メインループ(コマンド受付)を
統合する。Typerでサブコマンドを定義し、prompt_toolkitで補完付き入力、
Richで全ての表示を担当する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console

from promptagent.agent.agent_engine import AgentEngine
from promptagent.analyzer.project_analyzer import ProjectAnalysis, ProjectAnalyzer
from promptagent.config import Config
from promptagent.context.cache import SqliteCache, default_cache_path
from promptagent.context.context_builder import ContextBuilder
from promptagent.git.git_manager import GitManager, GitNotAvailableError
from promptagent.human_loop.loop import HumanLoop
from promptagent.hooks.hook_manager import HookEvent, HookManager
from promptagent.logging_setup import setup_logging
from promptagent.lsp.language_service import LanguageServiceRegistry
from promptagent.memory.memory_store import ConversationTurn, MemoryStore, Session
from promptagent.plugins.plugin_manager import PluginManager
from promptagent.prompt.json_schema import JsonContextFile, JsonPromptRequest
from promptagent.prompt.prompt_engine import PromptEngine, PromptRequest
from promptagent.ui import components
from promptagent.ui.command_palette import CommandPalette, PaletteItem
from promptagent.ui.splash import render_loading, render_splash

app = typer.Typer(add_completion=False, help="PromptAgent: 人間仲介型AI開発支援CLI")

_COMMANDS = [
    "/prompt", "/status", "/diff", "/commit", "/branch", "/stash", "/log",
    "/test", "/lint", "/tree", "/help", "/quit", "/sessions", "/plugins",
    "/find", "/goto", "/refs", "/symbols", "/tui", "/auto",
]


class PromptAgentApp:
    """メインループ全体を保持し進行させるアプリケーションクラス。"""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.console = Console()
        self.config = Config.load()
        self.logger = setup_logging(Path.home() / ".promptagent" / "logs", self.config.log_level)

        self.cache = SqliteCache(default_cache_path(self.project_root))
        self.analyzer = ProjectAnalyzer(
            ignore_patterns=self.config.context.ignore_patterns,
            max_file_size_kb=self.config.context.max_file_size_kb,
        )
        self.context_builder = ContextBuilder(
            max_tokens=self.config.context.max_tokens,
            cache=self.cache,
            priority_extensions=self.config.context.priority_extensions,
        )
        self.prompt_engine = PromptEngine()
        self.human_loop = HumanLoop(self.console, self.config.theme)
        self.hooks = HookManager()
        self.agent_engine = AgentEngine(self.project_root, self.config.agent, self.hooks)
        self.memory = MemoryStore()
        self.plugin_manager = PluginManager(self.project_root / "plugins")
        self.plugin_manager.load_all(self.hooks)
        self.palette = CommandPalette(self.console, self.config.theme)
        self.language_services = LanguageServiceRegistry(self.project_root)

        self.analysis: ProjectAnalysis | None = None
        self.session = Session.create(str(self.project_root))

        history_path = Path.home() / ".promptagent" / "history"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompt_session: PromptSession = PromptSession(
            history=FileHistory(str(history_path)),
            completer=WordCompleter(_COMMANDS, ignore_case=True, sentence=True),
        )

    def bootstrap(self) -> None:
        """スプラッシュ表示とプロジェクト解析を実行する。"""
        render_splash(self.console, self.config.theme)
        render_loading(self.console, self.config.theme, "プロジェクトを解析しています")

        cached = self.cache.get_project_analysis(str(self.project_root))
        if cached:
            self.analysis = ProjectAnalysis.from_dict(cached)
        else:
            self.analysis = self.analyzer.analyze(self.project_root)
            self.cache.set_project_analysis(str(self.project_root), self.analysis.to_dict())

        self._print_welcome()

    def _print_welcome(self) -> None:
        """解析結果のサマリを表示する。"""
        assert self.analysis is not None
        rows = [[lang, str(count)] for lang, count in sorted(
            self.analysis.language_counts.items(), key=lambda kv: kv[1], reverse=True
        )]
        table = components.render_table(self.config.theme, "検出言語", ["言語", "ファイル数"], rows)
        self.console.print(table)
        if self.analysis.manifests:
            self.console.print(f"[dim]マニフェスト: {', '.join(self.analysis.manifests)}[/dim]")
        self.console.print(
            f"[dim]{len(self.analysis.files)}ファイルを検出しました。/help でコマンド一覧を表示します。[/dim]\n"
        )

    def run(self) -> None:
        """メインの対話ループを実行する。"""
        self.bootstrap()
        while True:
            try:
                line = self.prompt_session.prompt("promptagent> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.console.print("\n[dim]終了します。[/dim]")
                break

            if not line:
                continue
            if not self._dispatch(line):
                break

        self.memory.save_session(self.session)
        self.cache.close()

    def _dispatch(self, line: str) -> bool:
        """入力されたコマンドを処理する。戻り値Falseでループ終了。"""
        command, _, rest = line.partition(" ")
        rest = rest.strip()

        handlers = {
            "/quit": self._cmd_quit,
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/diff": self._cmd_diff,
            "/commit": self._cmd_commit,
            "/branch": self._cmd_branch,
            "/stash": self._cmd_stash,
            "/log": self._cmd_log,
            "/test": self._cmd_test,
            "/lint": self._cmd_lint,
            "/tree": self._cmd_tree,
            "/sessions": self._cmd_sessions,
            "/plugins": self._cmd_plugins,
            "/find": self._cmd_find,
            "/goto": self._cmd_goto,
            "/refs": self._cmd_refs,
            "/symbols": self._cmd_symbols,
            "/tui": self._cmd_tui,
            "/auto": self._cmd_auto,
            "/prompt": lambda arg: self._cmd_prompt(arg),
        }

        handler = handlers.get(command)
        if handler is None:
            self.console.print(f"[yellow]不明なコマンドです: {command}[/yellow] (/help を参照)")
            return True
        return handler(rest)

    # -- 各コマンドの実装 -----------------------------------------------------

    def _cmd_quit(self, _rest: str) -> bool:
        return False

    def _cmd_help(self, _rest: str) -> bool:
        self.console.print(
            components.render_shortcut_help(
                self.config.theme,
                {
                    "AIへ送る指示を作成": "/prompt <指示文>",
                    "Gitステータス表示": "/status",
                    "Git差分表示": "/diff",
                    "コミット実行": "/commit <メッセージ>",
                    "ブランチ一覧/作成": "/branch [名前]",
                    "スタッシュ": "/stash",
                    "コミットログ": "/log",
                    "テスト実行": "/test",
                    "Lint実行": "/lint",
                    "ファイルツリー表示": "/tree",
                    "セッション一覧": "/sessions",
                    "プラグイン一覧": "/plugins",
                    "ファイルをあいまい検索": "/find <キーワード>",
                    "定義ジャンプ(Python)": "/goto <ファイル> <行> <列>",
                    "参照検索(Python)": "/refs <ファイル> <行> <列>",
                    "シンボル一覧(Python)": "/symbols <ファイル>",
                    "フルスクリーンUI起動": "/tui",
                    "自律コーディング(Google AI Studioのみ)": "/auto <指示文>",
                    "終了": "/quit",
                },
            )
        )
        return True

    def _cmd_status(self, _rest: str) -> bool:
        try:
            manager = GitManager(self.project_root)
            status = manager.status()
            rows = [
                ["ブランチ", status.branch],
                ["変更あり", "はい" if status.is_dirty else "いいえ"],
                ["未追跡ファイル", str(len(status.untracked_files))],
                ["変更ファイル", str(len(status.modified_files))],
                ["ステージ済み", str(len(status.staged_files))],
            ]
            self.console.print(components.render_table(self.config.theme, "Git Status", ["項目", "値"], rows))
        except GitNotAvailableError:
            self.console.print("[yellow]このディレクトリはGitリポジトリではありません。[/yellow]")
        return True

    def _cmd_diff(self, rest: str) -> bool:
        try:
            manager = GitManager(self.project_root)
            diff_text = manager.diff(staged=(rest == "--staged"))
            if diff_text:
                self.console.print(components.render_code(diff_text, "diff"))
            else:
                self.console.print("[dim]差分はありません。[/dim]")
        except GitNotAvailableError:
            self.console.print("[yellow]このディレクトリはGitリポジトリではありません。[/yellow]")
        return True

    def _cmd_commit(self, rest: str) -> bool:
        if not rest:
            self.console.print("[yellow]コミットメッセージを指定してください: /commit <メッセージ>[/yellow]")
            return True
        try:
            manager = GitManager(self.project_root)
            sha = manager.commit(rest)
            self.console.print(f"[green]✓ コミットしました: {sha[:8]}[/green]")
        except GitNotAvailableError:
            self.console.print("[yellow]このディレクトリはGitリポジトリではありません。[/yellow]")
        return True

    def _cmd_branch(self, rest: str) -> bool:
        try:
            manager = GitManager(self.project_root)
            if rest:
                manager.create_branch(rest)
                self.console.print(f"[green]✓ ブランチ {rest} を作成しました[/green]")
            else:
                for name in manager.branches():
                    self.console.print(f"  {name}")
        except GitNotAvailableError:
            self.console.print("[yellow]このディレクトリはGitリポジトリではありません。[/yellow]")
        return True

    def _cmd_stash(self, rest: str) -> bool:
        try:
            manager = GitManager(self.project_root)
            if rest == "pop":
                manager.stash_pop()
                self.console.print("[green]✓ スタッシュを復元しました[/green]")
            else:
                manager.stash(rest or None)
                self.console.print("[green]✓ 変更をスタッシュしました[/green]")
        except GitNotAvailableError:
            self.console.print("[yellow]このディレクトリはGitリポジトリではありません。[/yellow]")
        return True

    def _cmd_log(self, _rest: str) -> bool:
        try:
            manager = GitManager(self.project_root)
            rows = [[e.sha, e.author, e.date[:19], e.message] for e in manager.log()]
            self.console.print(components.render_table(self.config.theme, "コミットログ", ["SHA", "作者", "日時", "メッセージ"], rows))
        except GitNotAvailableError:
            self.console.print("[yellow]このディレクトリはGitリポジトリではありません。[/yellow]")
        return True

    def _cmd_test(self, _rest: str) -> bool:
        from promptagent.testing.test_runner import TestRunner

        runner = TestRunner(self.project_root)
        outcomes = runner.run_all()
        if not outcomes:
            self.console.print("[dim]テストランナーが検出されませんでした。[/dim]")
        for outcome in outcomes:
            style = "green" if outcome.all_passed else "red"
            self.console.print(f"[{style}]{outcome.runner_name}: exit={outcome.raw_result.exit_code}[/{style}]")
            self.console.print(outcome.raw_result.stdout[-2000:])
        return True

    def _cmd_lint(self, _rest: str) -> bool:
        from promptagent.lint.lint_runner import LintRunner

        runner = LintRunner(self.project_root)
        outcomes = runner.run_all()
        if not outcomes:
            self.console.print("[dim]Lintツールが検出されませんでした。[/dim]")
        for outcome in outcomes:
            style = "green" if outcome.is_clean else "red"
            self.console.print(f"[{style}]{outcome.tool_name}: exit={outcome.result.exit_code}[/{style}]")
            self.console.print(outcome.result.stdout[-2000:])
        return True

    def _cmd_tree(self, _rest: str) -> bool:
        assert self.analysis is not None
        tree = components.render_file_tree(self.config.theme, self.project_root, [f.path for f in self.analysis.files])
        self.console.print(tree)
        return True

    def _cmd_sessions(self, _rest: str) -> bool:
        sessions = self.memory.list_sessions()
        rows = [[s.session_id[:8], s.project_root, str(len(s.turns))] for s in sessions]
        self.console.print(components.render_table(self.config.theme, "セッション履歴", ["ID", "プロジェクト", "往復数"], rows))
        return True

    def _cmd_plugins(self, _rest: str) -> bool:
        plugins = self.plugin_manager.loaded_plugins
        if not plugins:
            self.console.print("[dim]プラグインは読み込まれていません。plugins/ にPythonファイルを配置してください。[/dim]")
        for plugin in plugins:
            self.console.print(f"  [cyan]{plugin.name}[/cyan]  ({plugin.path})")
        return True

    def _cmd_find(self, query: str) -> bool:
        assert self.analysis is not None
        items = [
            PaletteItem(
                label=str(f.path.relative_to(self.project_root)),
                description=f.language,
                payload=str(f.path),
            )
            for f in self.analysis.files
        ]
        selected = self.palette.select(items, query=query)
        if selected:
            self.console.print(f"[green]選択: {selected.label}[/green]")
        return True

    def _cmd_goto(self, rest: str) -> bool:
        parts = rest.split()
        if len(parts) != 3:
            self.console.print("[yellow]使い方: /goto <ファイル> <行> <列>[/yellow]")
            return True
        file_arg, line_str, column_str = parts
        file_path = (self.project_root / file_arg).resolve()
        backend = self.language_services.get_backend(file_path)
        if backend is None or not file_path.exists():
            self.console.print("[yellow]このファイルタイプの定義ジャンプには対応していません。[/yellow]")
            return True

        locations = backend.goto_definition(file_path, int(line_str), int(column_str))
        if not locations:
            self.console.print("[dim]定義が見つかりませんでした。[/dim]")
            return True
        rows = [[str(loc.file_path), str(loc.line), str(loc.column), loc.context_line] for loc in locations]
        self.console.print(components.render_table(self.config.theme, "定義ジャンプ", ["ファイル", "行", "列", "内容"], rows))
        return True

    def _cmd_symbols(self, rest: str) -> bool:
        if not rest:
            self.console.print("[yellow]使い方: /symbols <ファイル>[/yellow]")
            return True
        file_path = (self.project_root / rest).resolve()
        backend = self.language_services.get_backend(file_path)
        if backend is None or not file_path.exists():
            self.console.print("[yellow]このファイルタイプのシンボル解析には対応していません。[/yellow]")
            return True

        symbols = backend.list_symbols(file_path)
        rows = [[s.kind, s.name, str(s.location.line), s.signature] for s in symbols]
        self.console.print(components.render_table(self.config.theme, f"シンボル: {rest}", ["種別", "名前", "行", "シグネチャ"], rows))
        return True

    def _cmd_refs(self, rest: str) -> bool:
        parts = rest.split()
        if len(parts) != 3:
            self.console.print("[yellow]使い方: /refs <ファイル> <行> <列>[/yellow]")
            return True
        file_arg, line_str, column_str = parts
        file_path = (self.project_root / file_arg).resolve()
        backend = self.language_services.get_backend(file_path)
        if backend is None or not file_path.exists():
            self.console.print("[yellow]このファイルタイプの参照検索には対応していません。[/yellow]")
            return True

        locations = backend.find_references(file_path, int(line_str), int(column_str))
        if not locations:
            self.console.print("[dim]参照が見つかりませんでした。[/dim]")
            return True
        rows = [[str(loc.file_path), str(loc.line), str(loc.column), loc.context_line] for loc in locations]
        self.console.print(components.render_table(self.config.theme, "参照検索", ["ファイル", "行", "列", "内容"], rows))
        return True

    def _cmd_tui(self, _rest: str) -> bool:
        """フルスクリーンTextual UIを起動する(終了後は行指向CLIへ戻る)。"""
        from promptagent.ui.textual_app import PromptAgentTUI

        assert self.analysis is not None
        tui = PromptAgentTUI(cli_app=self)
        tui.run()
        return True

    def build_prompt_request(self, instruction: str) -> tuple[PromptRequest, str]:
        """指示文からPromptRequestとAIへ提示するプロンプト文字列を構築する。

        `config.prompt_format` が `"json"`(既定)の場合はJSON形式、
        `"markdown"` の場合は従来のMarkdown形式でプロンプト文字列を生成する。
        戻り値のPromptRequestには、AIへ提示した時点のファイル内容スナップショット
        (`context.files`)が含まれており、後続の競合検出(Agent Engine)で
        「AIへ送った後に外部でファイルが変更されていないか」を検証するのに使う。
        """
        assert self.analysis is not None

        self.hooks.fire(HookEvent.BEFORE_PROMPT, {"instruction": instruction, "project_root": str(self.project_root)})

        git_diff = ""
        git_status_summary = ""
        try:
            manager = GitManager(self.project_root)
            git_diff = manager.diff()
            status = manager.status()
            git_status_summary = f"branch={status.branch} dirty={status.is_dirty} modified={status.modified_files}"
        except GitNotAvailableError:
            pass

        context = self.context_builder.build(self.analysis, query_hint=instruction)
        request = PromptRequest(
            instruction=instruction,
            project_name=self.project_root.name,
            git_diff=git_diff,
            git_status_summary=git_status_summary,
            context=context,
        )

        if self.config.prompt_format == "json":
            prompt_text = self._to_json_prompt_request(request).to_json_string()
        else:
            prompt_text = self.prompt_engine.build(request)

        self.hooks.fire(HookEvent.AFTER_PROMPT, {"request": request, "prompt_text": prompt_text})
        return request, prompt_text

    def _to_json_prompt_request(self, request: PromptRequest) -> JsonPromptRequest:
        """PromptRequest(内部表現)をJSON送信用の `JsonPromptRequest` へ変換する。"""
        context_files: list[JsonContextFile] = []
        if request.context:
            for context_file in request.context.files:
                try:
                    relative = str(context_file.path.relative_to(self.project_root))
                except ValueError:
                    relative = str(context_file.path)
                context_files.append(
                    JsonContextFile(
                        path=relative,
                        language=context_file.language,
                        content=context_file.content,
                        truncated=context_file.truncated,
                    )
                )
        return JsonPromptRequest(
            instruction=request.instruction,
            project_name=request.project_name,
            git_diff=request.git_diff,
            git_status_summary=request.git_status_summary,
            test_output=request.test_output,
            lint_output=request.lint_output,
            error_output=request.error_output,
            context_files=context_files,
            extra_notes=request.extra_notes,
        )

    def _build_snapshots(self, request: PromptRequest) -> dict[str, str]:
        """PromptRequestのコンテキストからファイルスナップショットを構築する。"""
        if not request.context:
            return {}
        snapshots: dict[str, str] = {}
        for context_file in request.context.files:
            try:
                relative = str(context_file.path.relative_to(self.project_root))
            except ValueError:
                continue
            if not context_file.truncated:
                snapshots[relative] = context_file.content
        return snapshots

    def process_ai_response(
        self, prompt_text: str, response_text: str, request: PromptRequest | None = None
    ) -> object:
        """AI回答を受け取り、会話履歴保存とAgent Engineの実行までを行う。

        `config.prompt_format` に応じて、JSON専用パーサー(`run_cycle_json`)か
        従来のMarkdownパーサー(`run_cycle`)のどちらを使うかを自動判定する。
        """
        self.session.turns.append(
            ConversationTurn(prompt_text=prompt_text, response_text=response_text)
        )
        if not response_text.strip():
            return None
        snapshots = self._build_snapshots(request) if request else {}
        if self.config.prompt_format == "json":
            return self.agent_engine.run_cycle_json(response_text, snapshots=snapshots)
        return self.agent_engine.run_cycle(response_text, snapshots=snapshots)

    def _cmd_auto(self, instruction: str) -> bool:
        """自律コーディングループを起動する(Google AI Studio利用時のみ)。"""
        if not self.config.ai_backend.autonomous_available:
            self.console.print(
                "[yellow]自律コーディングはGoogle AI Studioを設定した場合のみ利用できます。\n"
                "config.yamlの`ai_backend.provider`を`google_ai_studio`に設定し、"
                "`ai_backend.api_key`(または環境変数)にAPIキーを設定してください。\n"
                "それ以外の場合は `/prompt` でHuman Loop(コピー&ペースト)をご利用ください。[/yellow]"
            )
            return True
        if not instruction:
            self.console.print("[yellow]指示文を入力してください: /auto <指示文>[/yellow]")
            return True

        from promptagent.autonomous.autonomous_runner import (
            AutonomousModeNotAvailableError,
            AutonomousRunner,
        )

        try:
            runner = AutonomousRunner(self)
        except AutonomousModeNotAvailableError as exc:
            self.console.print(f"[red]{exc}[/red]")
            return True

        self.console.print(
            f"[bold]自律コーディングを開始します[/bold] "
            f"(最大{self.config.ai_backend.max_autonomous_iterations}回反復, "
            f"モデル: {self.config.ai_backend.model})"
        )
        summary = runner.run(instruction)

        for log in summary.iterations:
            self.console.print(f"\n[bold #7C5CFF]--- 反復 {log.iteration} ---[/bold #7C5CFF]")
            if log.cycle_result.json_response:
                self.console.print(f"[dim]{log.cycle_result.json_response.summary}[/dim]")
            self._report_cycle_result(log.cycle_result)

        if summary.completed:
            self.console.print(f"\n[green]✓ 完了: {summary.stopped_reason}[/green]")
        else:
            self.console.print(f"\n[red]✗ 中断: {summary.stopped_reason}[/red]")
        return True

    def _cmd_prompt(self, instruction: str) -> bool:
        """指示文からプロンプトを生成し、Human Loopで一往復を実行する(行指向CLI用)。"""
        if not instruction:
            self.console.print("[yellow]指示文を入力してください: /prompt <指示文>[/yellow]")
            return True

        request, prompt_text = self.build_prompt_request(instruction)
        result = self.human_loop.run_round_trip(prompt_text)

        cycle_result = self.process_ai_response(result.prompt_text, result.response_text, request)
        if cycle_result is None:
            self.console.print("[dim]回答が空のため処理をスキップします。[/dim]")
            return True

        self._report_cycle_result(cycle_result)
        return True

    def _report_cycle_result(self, cycle_result) -> None:  # noqa: ANN001
        """Agent Engineの実行結果を表示する。"""
        for conflict in cycle_result.conflicts:
            if conflict.auto_merged:
                self.console.print(
                    f"[yellow]⚡ 自動マージ: {conflict.relative_path}[/yellow] - {conflict.reason}"
                )
            else:
                self.console.print(
                    f"[bold red]⚠ 競合(要手動解決): {conflict.relative_path}[/bold red] - {conflict.reason}"
                )

        for patch_result in cycle_result.patch_batch.results:
            if patch_result.applied:
                self.console.print(f"[green]✓ 適用: {patch_result.file_path}[/green]")
                if patch_result.old_content is not None:
                    self.console.print(
                        components.render_diff(
                            self.config.theme,
                            patch_result.old_content,
                            patch_result.new_content,
                            str(patch_result.file_path.relative_to(self.project_root)),
                        )
                    )
            else:
                self.console.print(f"[red]✗ 失敗: {patch_result.file_path} - {patch_result.error}[/red]")

        for outcome in cycle_result.test_outcomes:
            style = "green" if outcome.all_passed else "red"
            self.console.print(f"[{style}]テスト({outcome.runner_name}): passed={outcome.passed_count} failed={outcome.failed_count}[/{style}]")

        for outcome in cycle_result.lint_outcomes:
            style = "green" if outcome.is_clean else "yellow"
            self.console.print(f"[{style}]Lint({outcome.tool_name}): exit={outcome.result.exit_code}[/{style}]")

        if cycle_result.next_prompt_request:
            self.console.print(
                "[yellow]問題が検出されました。次のプロンプトを自動生成しました。"
                "'/prompt' で続けて送信できます。[/yellow]"
            )


@app.command()
def start(path: str = typer.Argument(".", help="プロジェクトルートのパス")) -> None:
    """PromptAgentを起動する(デフォルトコマンド)。"""
    project_root = Path(path)
    if not project_root.exists():
        typer.echo(f"指定されたパスが存在しません: {path}", err=True)
        raise typer.Exit(code=1)
    PromptAgentApp(project_root).run()


@app.command()
def version() -> None:
    """バージョン情報を表示する。"""
    from promptagent import __version__

    typer.echo(f"PromptAgent v{__version__}")


def main() -> None:
    """`promptagent` / `pa` コマンドのエントリポイント。"""
    if len(sys.argv) == 1:
        PromptAgentApp(Path(".")).run()
        return
    app()


if __name__ == "__main__":
    main()
