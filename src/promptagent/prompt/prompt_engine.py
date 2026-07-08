"""Prompt Engine。

プロジェクト情報・Git差分・エラー内容・実行結果・コンテキストファイルなど
必要な情報だけを収集し、Web版AIチャットへそのまま貼り付けられる
見やすいMarkdownプロンプトを自動生成する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from promptagent.context.context_builder import BuiltContext


@dataclass(slots=True)
class PromptRequest:
    """1回のプロンプト生成に必要な入力情報。"""

    instruction: str
    project_name: str = ""
    git_diff: str = ""
    git_status_summary: str = ""
    test_output: str = ""
    lint_output: str = ""
    error_output: str = ""
    context: BuiltContext | None = None
    extra_notes: list[str] = field(default_factory=list)


class PromptEngine:
    """収集した情報からMarkdown形式のプロンプトを組み立てるクラス。"""

    def build(self, request: PromptRequest) -> str:
        """`PromptRequest` からAIへ貼り付け可能なMarkdown文字列を生成する。"""
        sections: list[str] = []

        sections.append(f"# 開発依頼: {request.project_name or '(無題プロジェクト)'}")
        sections.append(f"## 指示\n{request.instruction.strip()}")

        if request.git_status_summary:
            sections.append(f"## Gitステータス\n```\n{request.git_status_summary.strip()}\n```")

        if request.git_diff:
            sections.append(f"## Git差分\n```diff\n{request.git_diff.strip()}\n```")

        if request.error_output:
            sections.append(f"## エラー内容\n```\n{request.error_output.strip()}\n```")

        if request.test_output:
            sections.append(f"## テスト結果\n```\n{request.test_output.strip()}\n```")

        if request.lint_output:
            sections.append(f"## Lint結果\n```\n{request.lint_output.strip()}\n```")

        if request.context and request.context.files:
            sections.append(f"## 関連ファイル (推定{request.context.estimated_tokens}トークン)")
            sections.append(request.context.to_markdown())

        if request.extra_notes:
            notes = "\n".join(f"- {note}" for note in request.extra_notes)
            sections.append(f"## 補足事項\n{notes}")

        sections.append(self._build_format_instructions())

        return "\n\n".join(sections)

    def _build_format_instructions(self) -> str:
        """回答フォーマットの指示セクションを構築する。

        PromptAgentのResponse Parserは特定のパターン(見出し直後のバックティック
        付きファイル名 → コードブロック)を検出してファイルへ自動適用する。
        AIがこの形式から外れると自動適用に失敗するため、具体例を示しながら
        「これ以外の形式は禁止」というレベルで厳密に指示する。
        """
        return (
            "## 回答フォーマット(必須・厳守)\n"
            "あなたの回答は自動処理システムによってパースされ、ファイルへ"
            "そのまま適用されます。以下のルールを**一字一句そのまま**守ってください。"
            "これ以外の形式で書かれた場合、変更は適用されません。\n\n"
            "### ルール1: ファイルの提示形式\n"
            "修正・新規作成する各ファイルについて、次の形式を**必ず**使用してください。\n"
            "見出しの直後に、コードブロック言語タグの直後に改行し、"
            "ファイルの**完全な内容**(冒頭から末尾まで、省略なし)を記述します。\n\n"
            "実際の記述例(このとおりの形式にしてください):\n\n"
            "````markdown\n"
            "### `src/app/main.py`\n"
            "```python\n"
            "# ここにファイルの完全な内容を書く(一部だけの抜粋は禁止)\n"
            "def main():\n"
            "    pass\n"
            "```\n"
            "````\n\n"
            "- `### `ファイルパス`` の行(見出しレベル3+バックティック)は**必ず**"
            "コードブロックの直前に置いてください。\n"
            "- ファイルパスはプロジェクトルートからの相対パスで記述してください"
            "(例: `src/app/main.py`)。絶対パスやプロジェクト外のパスは使用しないでください。\n"
            "- 1つのコードブロックには1ファイルの内容のみを含めてください。複数ファイルを"
            "1つのコードブロックにまとめないでください。\n"
            "- `# ... (変更なし)` や `# 以下省略` のような省略表現は**禁止**です。"
            "変更していない部分も含めて、そのファイルの完全な内容を毎回記述してください。\n"
            "- 新規作成するファイルも同じ形式(見出し+コードブロック)で記述してください。\n\n"
            "### ルール2: 実行すべきコマンド\n"
            "ターミナルで実行してほしいコマンドがある場合は、言語タグを"
            "`bash`としたコードブロックで示してください。コマンド以外"
            "(説明文やコメント記号 `#` を除く)をこのブロックに含めないでください。\n\n"
            "```bash\n"
            "pip install requests\n"
            "```\n\n"
            "### ルール3: 残作業の明記\n"
            "対応できなかった点や、後で人間が確認すべき点がある場合は、"
            "行頭に `TODO:` を付けた箇条書きで明記してください(例: `- TODO: 環境変数の設定が必要です`)。\n\n"
            "### ルール4: 説明文の位置\n"
            "変更内容の説明・要約は、コードブロックの**前後**(見出しの外)に自由に書いて構いません。"
            "ただし、コードブロックの**内部**には対象ファイルのコード以外を含めないでください。\n\n"
            "上記ルールに従えない特別な事情がある場合は、その理由を明記した上で、"
            "可能な範囲でルール1〜3の形式に近づけてください。"
        )

    def estimate_char_count(self, markdown_text: str) -> int:
        """生成したプロンプトの文字数を返す(コピー前の目安表示用)。"""
        return len(markdown_text)
