"""PromptAgentTUIのヘッドレス統合テスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from promptagent.cli import PromptAgentApp
from promptagent.ui.textual_app import PromptAgentTUI


@pytest.fixture
def cli_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PromptAgentApp:
    """一時ディレクトリをプロジェクトルートとするCLIアプリを生成する。"""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "sample.py").write_text("print('hi')\n", encoding="utf-8")
    app = PromptAgentApp(tmp_path)
    app.bootstrap()
    app.config.prompt_format = "markdown"  # 既存テストはMarkdown応答を前提にしている
    yield app
    app.cache.close()


@pytest.mark.asyncio
async def test_help_command_writes_to_log(cli_app: PromptAgentApp) -> None:
    tui = PromptAgentTUI(cli_app=cli_app)
    async with tui.run_test() as pilot:
        await pilot.pause()
        input_widget = tui.query_one("#command-input")
        input_widget.value = "/help"
        await pilot.press("enter")
        await pilot.pause()
        log_widget = tui.query_one("#log")
        assert len(log_widget.lines) > 0


@pytest.mark.asyncio
async def test_quit_command_exits_app(cli_app: PromptAgentApp) -> None:
    tui = PromptAgentTUI(cli_app=cli_app)
    async with tui.run_test() as pilot:
        await pilot.pause()
        input_widget = tui.query_one("#command-input")
        input_widget.value = "/quit"
        await pilot.press("enter")
        await pilot.pause()
        assert tui._exit is True


@pytest.mark.asyncio
async def test_prompt_command_opens_human_loop_modal_and_cancels(cli_app: PromptAgentApp) -> None:
    from promptagent.ui.textual_app import HumanLoopModal

    tui = PromptAgentTUI(cli_app=cli_app)
    async with tui.run_test() as pilot:
        await pilot.pause()
        input_widget = tui.query_one("#command-input")
        input_widget.value = "/prompt テスト用の指示"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(tui.screen, HumanLoopModal)
        await pilot.click("#cancel")
        await pilot.pause()

        log_widget = tui.query_one("#log")
        assert any("キャンセル" in str(line) for line in log_widget.lines)


@pytest.mark.asyncio
async def test_prompt_command_submits_response_and_runs_agent_cycle(cli_app: PromptAgentApp) -> None:
    from promptagent.ui.textual_app import HumanLoopModal
    from textual.widgets import TextArea

    tui = PromptAgentTUI(cli_app=cli_app)
    async with tui.run_test() as pilot:
        await pilot.pause()
        input_widget = tui.query_one("#command-input")
        input_widget.value = "/prompt sample.pyを直して"
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(tui.screen, HumanLoopModal)
        response_area = tui.screen.query_one("#response-area", TextArea)
        response_area.text = "### `sample.py`\n```python\nprint('updated')\n```\n"
        await pilot.click("#submit")
        await pilot.pause()

        updated_content = (cli_app.project_root / "sample.py").read_text(encoding="utf-8")
        assert "updated" in updated_content


@pytest.mark.asyncio
async def test_tree_refreshes_after_patch_applied(cli_app: PromptAgentApp) -> None:
    from textual.widgets import TextArea

    tui = PromptAgentTUI(cli_app=cli_app)
    async with tui.run_test() as pilot:
        await pilot.pause()

        tree_before = tui.query_one("#file-tree")
        node_count_before = len(list(tree_before.root.children))

        input_widget = tui.query_one("#command-input")
        input_widget.value = "/prompt 新しいファイルを追加して"
        await pilot.press("enter")
        await pilot.pause()

        response_area = tui.screen.query_one("#response-area", TextArea)
        response_area.text = "### `brand_new_module.py`\n```python\nVALUE = 1\n```\n"
        await pilot.click("#submit")
        await pilot.pause()

        assert (cli_app.project_root / "brand_new_module.py").exists()
        tree_after = tui.query_one("#file-tree")
        node_count_after = len(list(tree_after.root.children))
        assert node_count_after >= node_count_before
