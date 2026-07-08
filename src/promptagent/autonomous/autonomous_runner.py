"""自律コーディングエンジン(Google AI Studio専用)。

`config.ai_backend.provider == "google_ai_studio"` のときのみ利用可能な、
Human Loopを介さずAIとの往復を自動化するAgent Loopを提供する。

意図的に他のAI API(OpenAI/Anthropic等)やローカルLLMには対応しない。
Google AI Studio(Gemini API)を明示的に選んだ場合に限り、以下のループを
人間の介入なしに繰り返す:

    プロンプト生成(JSON) → Gemini API呼び出し → JSON応答パース →
    ファイル適用 → テスト/Lint → (完了 or 問題あり) → 次のプロンプトへ

利用者はこの自動化に同意した上で明示的にオプトインする必要がある
(`ai_backend.provider: google_ai_studio` を設定した場合のみ有効)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from promptagent.ai_backend.gemini_client import GeminiAPIError, GeminiClient
from promptagent.config import AIBackendConfig

if TYPE_CHECKING:
    from promptagent.agent.agent_engine import AgentCycleResult
    from promptagent.cli import PromptAgentApp


class AutonomousModeNotAvailableError(RuntimeError):
    """Google AI Studio以外のバックエンドで自律モードが要求された場合に送出される。"""


@dataclass(slots=True)
class AutonomousIterationLog:
    """自律ループ1回分の記録。"""

    iteration: int
    instruction: str
    cycle_result: "AgentCycleResult"


@dataclass(slots=True)
class AutonomousRunSummary:
    """自律ループ全体の実行結果サマリ。"""

    iterations: list[AutonomousIterationLog] = field(default_factory=list)
    completed: bool = False
    stopped_reason: str = ""

    @property
    def iteration_count(self) -> int:
        """実行された反復回数。"""
        return len(self.iterations)


class AutonomousRunner:
    """Google AI Studio(Gemini API)を用いた自律コーディングループを実行するクラス。"""

    def __init__(self, cli_app: "PromptAgentApp", gemini_client: GeminiClient | None = None) -> None:
        ai_backend_config: AIBackendConfig = cli_app.config.ai_backend
        if not ai_backend_config.autonomous_available:
            raise AutonomousModeNotAvailableError(
                "自律コーディングはGoogle AI Studio(ai_backend.provider: google_ai_studio)"
                "を設定した場合のみ利用できます。"
            )

        self._cli_app = cli_app
        self._client = gemini_client or GeminiClient(
            api_key=ai_backend_config.resolve_api_key(),
            model=ai_backend_config.model,
            timeout_seconds=ai_backend_config.request_timeout_seconds,
            temperature=ai_backend_config.temperature,
        )
        self._max_iterations = ai_backend_config.max_autonomous_iterations

    def run(self, instruction: str, *, max_iterations: int | None = None) -> AutonomousRunSummary:
        """指示文から自律コーディングループを開始する。"""
        summary = AutonomousRunSummary()
        limit = max_iterations or self._max_iterations
        current_instruction = instruction

        for iteration in range(1, limit + 1):
            request, prompt_json_text = self._cli_app.build_prompt_request(current_instruction)

            try:
                gemini_response = self._client.generate(prompt_json_text)
            except GeminiAPIError as exc:
                summary.stopped_reason = f"Gemini API呼び出しに失敗しました: {exc}"
                break

            cycle_result = self._cli_app.process_ai_response(
                prompt_json_text, gemini_response.text, request
            )
            if cycle_result is None:
                summary.stopped_reason = "AIの回答が空でした"
                break

            summary.iterations.append(
                AutonomousIterationLog(
                    iteration=iteration, instruction=current_instruction, cycle_result=cycle_result
                )
            )

            if cycle_result.task_complete and cycle_result.next_prompt_request is None:
                summary.completed = True
                summary.stopped_reason = "AIがタスク完了と判断しました"
                break

            if cycle_result.next_prompt_request is None:
                # 完了フラグは立っていないが、追加対応も不要と判断された場合。
                summary.completed = True
                summary.stopped_reason = "追加の問題は検出されませんでした"
                break

            current_instruction = cycle_result.next_prompt_request.instruction
            if cycle_result.next_prompt_request.error_output:
                current_instruction += "\n\n" + cycle_result.next_prompt_request.error_output
        else:
            summary.stopped_reason = f"最大反復回数({limit}回)に達しました"

        return summary
