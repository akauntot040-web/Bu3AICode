"""PatchEngineの単体テスト。"""

from __future__ import annotations

from pathlib import Path

from promptagent.patch.patch_engine import PatchEngine


def test_apply_creates_new_file(tmp_path: Path) -> None:
    engine = PatchEngine(tmp_path)
    batch = engine.apply({"new_file.py": "print('new')\n"})
    assert len(batch.succeeded) == 1
    assert (tmp_path / "new_file.py").read_text(encoding="utf-8") == "print('new')\n"


def test_apply_backs_up_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("old_content\n", encoding="utf-8")

    engine = PatchEngine(tmp_path)
    batch = engine.apply({"existing.py": "new_content\n"})

    result = batch.succeeded[0]
    assert result.backup_path is not None
    assert result.backup_path.read_text(encoding="utf-8") == "old_content\n"
    assert target.read_text(encoding="utf-8") == "new_content\n"


def test_rollback_restores_original_content(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("old_content\n", encoding="utf-8")

    engine = PatchEngine(tmp_path)
    batch = engine.apply({"existing.py": "new_content\n"})
    engine.rollback(batch)

    assert target.read_text(encoding="utf-8") == "old_content\n"


def test_apply_rejects_path_outside_project_root(tmp_path: Path) -> None:
    engine = PatchEngine(tmp_path)
    batch = engine.apply({"../outside.py": "malicious\n"})
    assert len(batch.failed) == 1
    assert not (tmp_path.parent / "outside.py").exists()
