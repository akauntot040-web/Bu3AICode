"""Agent Engine。

AIの回答を受け取った後の一連の作業（ファイル更新・テスト・Lint・型チェック・
Git Diff・エラー解析・次のプロンプト生成）を全自動で実行する。
AIを呼び出す部分（プロンプト提示直前）だけが人間仲介ポイントとして残る
(ただしGoogle AI Studio利用時は、その部分すら自律ループへ組み込める。
`autonomous/autonomous_runner.py` を参照)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from promptagent.config import AgentConfig
from promptagent.git.git_manager import GitManager, GitNotAvailableError
from promptagent.hooks.hook_manager import HookEvent, HookManager
from promptagent.lint.lint_runner import LintOutcome, LintRunner
from promptagent.parser.response_parser import ParsedResponse, ResponseParser
from promptagent.patch.patch_engine import PatchBatch, PatchEngine
from promptagent.patch.three_way_merge import MergeStatus, three_way_merge
from promptagent.prompt.json_schema import JsonParsedResponse, JsonResponseParser
from promptagent.prompt.prompt_engine import PromptRequest
from promptagent.testing.test_runner import TestOutcome, TestRunner


@dataclass(slots=True)
class ConflictInfo:
    """AIへ提示した後に外部でファイルが変更されていたことを示す情報。"""

    relative_path: str
    reason: str
    auto_merged: bool = False
    merge_conflict_markers: int = 0


@dataclass(slots=True)
class AgentCycleResult:
    """AI回答受信〜次プロンプト準備までの1サイクルの結果。

    Markdown形式(`run_cycle`)とJSON形式(`run_cycle_json`)のどちらの経路でも
    共通して利用できるよう、由来に応じて `parsed_response` か `json_response`
    のどちらか一方が設定される。
    """

    patch_batch: PatchBatch
    parsed_response: ParsedResponse | None = None
    json_response: JsonParsedResponse | None = None
    test_outcomes: list[TestOutcome] = field(default_factory=list)
    lint_outcomes: list[LintOutcome] = field(default_factory=list)
    git_diff: str = ""
    conflicts: list[ConflictInfo] = field(default_factory=list)
    next_prompt_request: PromptRequest | None = None

    @property
    def task_complete(self) -> bool:
        """JSON経路の場合、AI自身が「作業完了」と判断したかどうか。"""
        return bool(self.json_response and self.json_response.task_complete)


class AgentEngine:
    """AI以外の作業を全自動で実行するオーケストレータ。"""

    def __init__(
        self,
        project_root: Path,
        config: AgentConfig,
        hook_manager: HookManager | None = None,
    ) -> None:
        self._project_root = project_root
        self._config = config
        self._hooks = hook_manager or HookManager()
        self._parser = ResponseParser()
        self._json_parser = JsonResponseParser()
        self._patch_engine = PatchEngine(project_root)
        self._test_runner = TestRunner(project_root)
        self._lint_runner = LintRunner(project_root)

    def run_cycle(
        self, response_text: str, *, dry_run: bool = False, snapshots: dict[str, str] | None = None
    ) -> AgentCycleResult:
        """AI回答テキスト(Markdown形式)を受け取り、パース〜検証〜次プロンプト生成までを実行する。

        `snapshots` にAIへ提示した時点のファイル内容(相対パス→内容)を渡すと、
        適用前に「AIへ送った後に外部で変更されていないか」の競合検出を行い、
        3-wayマージを試みる。
        """
        self._hooks.fire(HookEvent.BEFORE_PATCH, {"response_text": response_text})
        parsed = self._parser.parse(response_text)

        result = self._run_cycle_core(dict(parsed.file_patches), snapshots or {}, dry_run=dry_run)
        result.parsed_response = parsed
        return result

    def run_cycle_json(
        self, response_json_text: str, *, dry_run: bool = False, snapshots: dict[str, str] | None = None
    ) -> AgentCycleResult:
        """AI回答テキスト(JSON形式)を受け取り、パース〜検証〜次プロンプト生成までを実行する。

        Google AI Studio利用時など、`prompt_format: json` のレスポンスに対して使う。
        パースはMarkdown経路と違い正規表現を使わず、`json.loads`とスキーマ検証のみで
        行われるため、AIの出力ゆらぎに対して頑健。
        """
        self._hooks.fire(HookEvent.BEFORE_PATCH, {"response_text": response_json_text})
        parsed = self._json_parser.parse(response_json_text)

        result = self._run_cycle_core(dict(parsed.file_patches), snapshots or {}, dry_run=dry_run)
        result.json_response = parsed
        return result

    def _run_cycle_core(
        self, file_patches: dict[str, str], snapshots: dict[str, str], *, dry_run: bool
    ) -> AgentCycleResult:
        """パース済みのファイルパッチ辞書からパッチ適用〜次プロンプト生成までを行う共通処理。"""
        conflicts = self._resolve_conflicts(file_patches, snapshots)

        patch_batch = self._patch_engine.apply(file_patches, dry_run=dry_run)
        self._hooks.fire(HookEvent.AFTER_PATCH, {"batch": patch_batch})

        result = AgentCycleResult(patch_batch=patch_batch, conflicts=conflicts)

        if self._config.auto_run_tests and not dry_run:
            self._hooks.fire(HookEvent.BEFORE_TEST)
            result.test_outcomes = self._test_runner.run_all()
            self._hooks.fire(HookEvent.AFTER_TEST, {"outcomes": result.test_outcomes})

        if self._config.auto_run_lint and not dry_run:
            self._hooks.fire(HookEvent.BEFORE_LINT)
            result.lint_outcomes = self._lint_runner.run_all()
            self._hooks.fire(HookEvent.AFTER_LINT, {"outcomes": result.lint_outcomes})

        if self._config.auto_git_diff and not dry_run:
            result.git_diff = self._safe_git_diff()

        result.next_prompt_request = self._build_followup_request(result)
        return result

    def _resolve_conflicts(
        self, file_patches: dict[str, str], snapshots: dict[str, str]
    ) -> list[ConflictInfo]:
        """AIへ提示した後に外部変更されたファイルについて3-wayマージを試みる。

        `file_patches` は内部で書き換えられる(呼び出し元の辞書を直接更新する):
        - 自動マージに成功した場合、マージ後の内容へ更新する
        - 競合マーカーが必要な場合、マーカー付きの内容へ更新し、人間による
          解決を促す(パッチ適用自体は行い、ファイル内に競合マーカーを残す)
        """
        conflicts: list[ConflictInfo] = []
        for relative_path, proposed_content in list(file_patches.items()):
            if relative_path not in snapshots:
                continue

            base_text = snapshots[relative_path]
            current_text = self._read_current_content(relative_path)
            if current_text is None or current_text == base_text:
                continue  # 外部変更なし、または新規ファイルなので競合しない

            merge_result = three_way_merge(base_text, current_text, proposed_content)

            if merge_result.status == MergeStatus.CLEAN:
                file_patches[relative_path] = merge_result.merged_text
                conflicts.append(
                    ConflictInfo(
                        relative_path=relative_path,
                        reason="外部変更とAI提案が重複しなかったため自動マージしました",
                        auto_merged=True,
                    )
                )
            elif merge_result.status == MergeStatus.CONFLICT:
                file_patches[relative_path] = merge_result.merged_text
                conflicts.append(
                    ConflictInfo(
                        relative_path=relative_path,
                        reason=(
                            f"外部変更とAI提案が重複したため、競合マーカーを挿入しました"
                            f"(要手動解決: {merge_result.conflict_count}箇所)"
                        ),
                        auto_merged=False,
                        merge_conflict_markers=merge_result.conflict_count,
                    )
                )
        return conflicts

    def _read_current_content(self, relative_path: str) -> str | None:
        """プロジェクトルート配下のファイルの現在の内容を読み込む。"""
        target_path = (self._project_root / relative_path).resolve()
        if not target_path.exists():
            return None
        try:
            return target_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def _safe_git_diff(self) -> str:
        """Gitリポジトリが存在する場合のみdiffを取得する。"""
        try:
            manager = GitManager(self._project_root)
            return manager.diff()
        except GitNotAvailableError:
            return ""

    def _build_followup_request(self, result: AgentCycleResult) -> PromptRequest | None:
        """テスト失敗やLint指摘があれば、次に送るべきプロンプトの下書きを作る。"""
        failing_tests = [o for o in result.test_outcomes if not o.all_passed]
        failing_lints = [o for o in result.lint_outcomes if not o.is_clean]
        unresolved_conflicts = [c for c in result.conflicts if not c.auto_merged]

        if not failing_tests and not failing_lints and not result.patch_batch.failed and not unresolved_conflicts:
            return None

        error_parts: list[str] = []
        for outcome in failing_tests:
            error_parts.append(f"[{outcome.runner_name}]\n{outcome.raw_result.stdout}\n{outcome.raw_result.stderr}")
        for outcome in failing_lints:
            error_parts.append(f"[{outcome.tool_name}]\n{outcome.result.stdout}\n{outcome.result.stderr}")
        for failed_patch in result.patch_batch.failed:
            error_parts.append(f"パッチ適用失敗: {failed_patch.file_path} - {failed_patch.error}")
        for conflict in unresolved_conflicts:
            error_parts.append(
                f"競合(手動解決が必要): {conflict.relative_path} - {conflict.reason}\n"
                f"ファイル内の <<<<<<< / ======= / >>>>>>> マーカーを解消してください。"
            )

        return PromptRequest(
            instruction="前回の修正後に発生した以下の問題を修正してください。",
            error_output="\n\n".join(error_parts),
            git_diff=result.git_diff,
        )
