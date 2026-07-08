"""Patch Engine。

パース済みのファイルパッチを既存プロジェクトへ安全に適用する。適用前には
バックアップを取得し、いつでもロールバック可能な状態を維持する。また、
適用前後の差分をRichで表示するためのデータも生成する。
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PatchResult:
    """1ファイルに対するパッチ適用結果。"""

    file_path: Path
    old_content: str | None
    new_content: str
    is_new_file: bool
    applied: bool
    backup_path: Path | None = None
    error: str | None = None


@dataclass(slots=True)
class PatchBatch:
    """複数ファイルへの一括パッチ適用結果。"""

    results: list[PatchResult] = field(default_factory=list)
    batch_id: str = ""

    @property
    def succeeded(self) -> list[PatchResult]:
        """適用に成功した結果のみ返す。"""
        return [r for r in self.results if r.applied]

    @property
    def failed(self) -> list[PatchResult]:
        """適用に失敗した結果のみ返す。"""
        return [r for r in self.results if not r.applied]


class PatchEngine:
    """ファイルパッチの適用・ロールバックを担当するクラス。"""

    def __init__(self, project_root: Path, backup_dir: Path | None = None) -> None:
        self._project_root = project_root
        self._backup_dir = backup_dir or (project_root / ".promptagent" / "backups")

    def apply(self, file_patches: dict[str, str], *, dry_run: bool = False) -> PatchBatch:
        """複数ファイルへパッチを一括適用する。"""
        batch_id = time.strftime("%Y%m%d_%H%M%S")
        batch = PatchBatch(batch_id=batch_id)

        for relative_path, new_content in file_patches.items():
            result = self._apply_single(relative_path, new_content, batch_id, dry_run=dry_run)
            batch.results.append(result)

        return batch

    def _apply_single(
        self, relative_path: str, new_content: str, batch_id: str, *, dry_run: bool
    ) -> PatchResult:
        """1ファイルへパッチを適用する内部処理。"""
        target_path = (self._project_root / relative_path).resolve()

        if not str(target_path).startswith(str(self._project_root.resolve())):
            return PatchResult(
                file_path=target_path,
                old_content=None,
                new_content=new_content,
                is_new_file=False,
                applied=False,
                error="プロジェクトルート外への書き込みは許可されていません",
            )

        is_new_file = not target_path.exists()
        old_content: str | None = None
        backup_path: Path | None = None

        if not is_new_file:
            try:
                old_content = target_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return PatchResult(
                    file_path=target_path,
                    old_content=None,
                    new_content=new_content,
                    is_new_file=False,
                    applied=False,
                    error=f"既存ファイルの読み込みに失敗しました: {exc}",
                )

        if dry_run:
            return PatchResult(
                file_path=target_path,
                old_content=old_content,
                new_content=new_content,
                is_new_file=is_new_file,
                applied=False,
            )

        try:
            if not is_new_file:
                backup_path = self._create_backup(target_path, batch_id)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return PatchResult(
                file_path=target_path,
                old_content=old_content,
                new_content=new_content,
                is_new_file=is_new_file,
                applied=False,
                error=f"書き込みに失敗しました: {exc}",
            )

        return PatchResult(
            file_path=target_path,
            old_content=old_content,
            new_content=new_content,
            is_new_file=is_new_file,
            applied=True,
            backup_path=backup_path,
        )

    def _create_backup(self, target_path: Path, batch_id: str) -> Path:
        """既存ファイルのバックアップを作成する。"""
        relative = target_path.relative_to(self._project_root.resolve())
        backup_path = self._backup_dir / batch_id / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target_path, backup_path)
        return backup_path

    def rollback(self, batch: PatchBatch) -> list[Path]:
        """バッチ内の全変更をロールバックする。新規作成ファイルは削除する。"""
        restored: list[Path] = []
        for result in batch.succeeded:
            if result.is_new_file:
                if result.file_path.exists():
                    result.file_path.unlink()
                    restored.append(result.file_path)
            elif result.backup_path and result.backup_path.exists():
                shutil.copy2(result.backup_path, result.file_path)
                restored.append(result.file_path)
        return restored

    def detect_conflict(self, relative_path: str, expected_old_content: str) -> bool:
        """パッチ生成後にファイルが外部で変更されていないか(競合)を検出する。"""
        target_path = (self._project_root / relative_path).resolve()
        if not target_path.exists():
            return expected_old_content != ""
        current_content = target_path.read_text(encoding="utf-8", errors="replace")
        return current_content != expected_old_content
