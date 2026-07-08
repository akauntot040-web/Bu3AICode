"""Git操作マネージャ。

GitPythonをラップし、status/diff/commit/checkout/branch/stash/log/blame/merge/
rebaseなど、開発でよく使う操作を型安全なAPIとして提供する。

GitPythonは `import git` 時点で `git` 実行ファイルをPATHから解決しようとし、
見つからない場合は `ImportError` を送出してプロセス全体を止めてしまう。
PromptAgentはGitが未インストールの環境でも他機能が動作すべきなので、
インポート時の例外を吸収し、実際にGit機能が使われたタイミングで初めて
`GitNotAvailableError` を送出するようにしている。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# GitPythonが起動時に警告メッセージ/例外を出すのを抑止し、GitNotAvailableError
# として一元的に扱えるようにする(既に設定されている場合は上書きしない)。
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")


@dataclass(slots=True)
class GitStatus:
    """git status相当の情報。"""

    branch: str
    is_dirty: bool
    untracked_files: list[str]
    modified_files: list[str]
    staged_files: list[str]


@dataclass(slots=True)
class GitLogEntry:
    """コミットログの1エントリ。"""

    sha: str
    author: str
    message: str
    date: str


class GitNotAvailableError(RuntimeError):
    """対象ディレクトリがGitリポジトリでない、またはGit自体が利用できない場合に送出される。"""


class GitManager:
    """Gitリポジトリに対する操作をまとめたマネージャクラス。"""

    def __init__(self, root: Path) -> None:
        try:
            from git import Repo
            from git.exc import InvalidGitRepositoryError
        except ImportError as exc:
            raise GitNotAvailableError(
                "Gitが見つかりません。Gitをインストールし、PATHへ追加してください。"
            ) from exc

        try:
            self._repo = Repo(str(root), search_parent_directories=True)
        except InvalidGitRepositoryError as exc:
            raise GitNotAvailableError(f"{root} はGitリポジトリではありません") from exc

    @property
    def is_available(self) -> bool:
        """リポジトリが利用可能かどうか。"""
        return self._repo is not None

    def status(self) -> GitStatus:
        """現在のブランチと変更ファイル一覧を取得する。"""
        try:
            branch = self._repo.active_branch.name
        except TypeError:
            branch = "(detached HEAD)"
        diff_index = self._repo.index.diff(None)
        staged = self._repo.index.diff("HEAD") if self._repo.head.is_valid() else []
        return GitStatus(
            branch=branch,
            is_dirty=self._repo.is_dirty(untracked_files=True),
            untracked_files=list(self._repo.untracked_files),
            modified_files=[item.a_path for item in diff_index],
            staged_files=[item.a_path for item in staged],
        )

    def diff(self, staged: bool = False, path: str | None = None) -> str:
        """作業ツリーまたはステージ済み変更のユニファイド差分を取得する。"""
        args = ["--cached"] if staged else []
        if path:
            args.append(path)
        return self._repo.git.diff(*args)

    def commit(self, message: str, add_all: bool = True) -> str:
        """変更をコミットし、コミットSHAを返す。"""
        if add_all:
            self._repo.git.add(all=True)
        commit = self._repo.index.commit(message)
        return commit.hexsha

    def checkout(self, ref: str, create: bool = False) -> None:
        """ブランチまたはコミットをチェックアウトする。"""
        if create:
            self._repo.git.checkout("-b", ref)
        else:
            self._repo.git.checkout(ref)

    def branches(self) -> list[str]:
        """ローカルブランチ一覧を取得する。"""
        return [head.name for head in self._repo.heads]

    def create_branch(self, name: str) -> None:
        """新しいブランチを作成する。"""
        self._repo.create_head(name)

    def stash(self, message: str | None = None) -> None:
        """変更をスタッシュする。"""
        if message:
            self._repo.git.stash("push", "-m", message)
        else:
            self._repo.git.stash("push")

    def stash_pop(self) -> None:
        """直近のスタッシュを適用する。"""
        self._repo.git.stash("pop")

    def log(self, max_count: int = 20) -> list[GitLogEntry]:
        """直近のコミットログを取得する。"""
        entries = []
        for commit in self._repo.iter_commits(max_count=max_count):
            entries.append(
                GitLogEntry(
                    sha=commit.hexsha[:8],
                    author=str(commit.author),
                    message=commit.message.strip().splitlines()[0],
                    date=commit.committed_datetime.isoformat(),
                )
            )
        return entries

    def blame(self, file_path: str) -> list[tuple[str, str]]:
        """ファイルの各行に対するコミット情報を取得する。"""
        from git.exc import GitCommandError

        results = []
        try:
            for commit, lines in self._repo.blame("HEAD", file_path):
                for line in lines:
                    results.append((commit.hexsha[:8], line))
        except GitCommandError:
            return []
        return results

    def merge(self, branch: str) -> None:
        """指定ブランチを現在のブランチへマージする。"""
        self._repo.git.merge(branch)

    def rebase(self, branch: str) -> None:
        """現在のブランチを指定ブランチへリベースする。"""
        self._repo.git.rebase(branch)
