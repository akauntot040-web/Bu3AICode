"""3-wayマージユーティリティ。

「AIへ提示した時点の内容(base)」「その後に外部で変更された現在の内容(theirs)」
「AIが提案した新しい内容(ours)」の3つを比較し、変更箇所が重複していなければ
自動マージを試みる。重複する変更がある場合は、Gitスタイルの競合マーカーを
挿入したテキストを返し、人間による解決を促す。
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum, auto


class MergeStatus(Enum):
    """マージ結果の種別。"""

    CLEAN = auto()
    """変更が重複せず、自動マージに成功した。"""
    CONFLICT = auto()
    """変更が重複し、手動解決が必要な競合マーカー付きテキストを返した。"""
    NO_CHANGE = auto()
    """base/theirs/oursが全て同一で、変更自体がなかった。"""


@dataclass(slots=True)
class MergeResult:
    """3-wayマージの結果。"""

    status: MergeStatus
    merged_text: str
    conflict_count: int = 0


def three_way_merge(base_text: str, theirs_text: str, ours_text: str) -> MergeResult:
    """base/theirs/oursの3つのテキストから3-wayマージを試みる。

    - base: AIへ提示した時点の内容
    - theirs: その後に外部で変更された現在の内容
    - ours: AIが提案した新しい内容
    """
    if base_text == theirs_text == ours_text:
        return MergeResult(status=MergeStatus.NO_CHANGE, merged_text=base_text)
    if theirs_text == base_text:
        # 外部変更がないので、AI提案をそのまま採用してよい。
        return MergeResult(status=MergeStatus.CLEAN, merged_text=ours_text)
    if ours_text == base_text:
        # AI提案がbaseと同一(変更なし)なので、外部変更(theirs)を維持する。
        return MergeResult(status=MergeStatus.CLEAN, merged_text=theirs_text)

    base_lines = base_text.splitlines(keepends=True)
    theirs_lines = theirs_text.splitlines(keepends=True)
    ours_lines = ours_text.splitlines(keepends=True)

    theirs_ops = [op for op in difflib.SequenceMatcher(None, base_lines, theirs_lines).get_opcodes() if op[0] != "equal"]
    ours_ops = [op for op in difflib.SequenceMatcher(None, base_lines, ours_lines).get_opcodes() if op[0] != "equal"]

    # (base開始, base終了) の変更区間をtheirs/oursの双方から集め、重複するものを
    # 1つのグループへ統合する(単純な区間統合アルゴリズム)。
    raw_intervals = sorted({(op[1], op[2]) for op in theirs_ops} | {(op[1], op[2]) for op in ours_ops})
    merged_groups: list[tuple[int, int]] = []
    for start, end in raw_intervals:
        if merged_groups and start < merged_groups[-1][1]:
            prev_start, prev_end = merged_groups[-1]
            merged_groups[-1] = (prev_start, max(prev_end, end))
        else:
            merged_groups.append((start, end))

    merged_lines: list[str] = []
    conflict_count = 0
    cursor = 0

    for group_start, group_end in merged_groups:
        if group_start > cursor:
            merged_lines.extend(base_lines[cursor:group_start])

        theirs_segment = _build_segment(theirs_ops, theirs_lines, base_lines, group_start, group_end)
        ours_segment = _build_segment(ours_ops, ours_lines, base_lines, group_start, group_end)

        if theirs_segment == ours_segment:
            merged_lines.extend(theirs_segment)
        elif theirs_segment == base_lines[group_start:group_end]:
            merged_lines.extend(ours_segment)
        elif ours_segment == base_lines[group_start:group_end]:
            merged_lines.extend(theirs_segment)
        else:
            conflict_count += 1
            merged_lines.append("<<<<<<< THEIRS (外部変更)\n")
            merged_lines.extend(theirs_segment)
            merged_lines.append("=======\n")
            merged_lines.extend(ours_segment)
            merged_lines.append(">>>>>>> OURS (AI提案)\n")

        cursor = group_end

    merged_lines.extend(base_lines[cursor:len(base_lines)])

    status = MergeStatus.CONFLICT if conflict_count > 0 else MergeStatus.CLEAN
    return MergeResult(status=status, merged_text="".join(merged_lines), conflict_count=conflict_count)


def _build_segment(
    ops: list, side_lines: list[str], base_lines: list[str], group_start: int, group_end: int
) -> list[str]:
    """指定opcode群のうち [group_start, group_end) に重なる変更を組み立てて返す。

    重ならない部分はbaseの内容で埋め、グループ全体としての「変更後の見た目」を再現する。
    """
    segment: list[str] = []
    cursor = group_start
    for tag, base_start, base_end, side_start, side_end in ops:
        if base_end <= group_start or base_start >= group_end:
            continue
        clipped_start = max(base_start, group_start)
        if clipped_start > cursor:
            segment.extend(base_lines[cursor:clipped_start])
        segment.extend(side_lines[side_start:side_end])
        cursor = min(base_end, group_end)
    if cursor < group_end:
        segment.extend(base_lines[cursor:group_end])
    return segment
