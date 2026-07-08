"""three_way_mergeの単体テスト。"""

from __future__ import annotations

from promptagent.patch.three_way_merge import MergeStatus, three_way_merge


def test_no_change_when_all_identical() -> None:
    text = "a\nb\nc\n"
    result = three_way_merge(text, text, text)
    assert result.status == MergeStatus.NO_CHANGE
    assert result.merged_text == text


def test_clean_when_only_ours_changed() -> None:
    base = "a\nb\nc\n"
    theirs = base
    ours = "a\nCHANGED\nc\n"
    result = three_way_merge(base, theirs, ours)
    assert result.status == MergeStatus.CLEAN
    assert result.merged_text == ours


def test_clean_when_only_theirs_changed() -> None:
    base = "a\nb\nc\n"
    theirs = "a\nCHANGED\nc\n"
    ours = base
    result = three_way_merge(base, theirs, ours)
    assert result.status == MergeStatus.CLEAN
    assert result.merged_text == theirs


def test_clean_merge_when_changes_do_not_overlap() -> None:
    base = "line1\nline2\nline3\nline4\nline5\n"
    theirs = "line1\nCHANGED_THEIRS\nline3\nline4\nline5\n"
    ours = "line1\nline2\nline3\nline4\nCHANGED_OURS\n"
    result = three_way_merge(base, theirs, ours)
    assert result.status == MergeStatus.CLEAN
    assert "CHANGED_THEIRS" in result.merged_text
    assert "CHANGED_OURS" in result.merged_text


def test_conflict_when_changes_overlap() -> None:
    base = "line1\nline2\nline3\n"
    theirs = "line1\nCHANGED_THEIRS\nline3\n"
    ours = "line1\nCHANGED_OURS\nline3\n"
    result = three_way_merge(base, theirs, ours)
    assert result.status == MergeStatus.CONFLICT
    assert result.conflict_count == 1
    assert "<<<<<<< THEIRS" in result.merged_text
    assert "CHANGED_THEIRS" in result.merged_text
    assert "CHANGED_OURS" in result.merged_text
    assert ">>>>>>> OURS" in result.merged_text
