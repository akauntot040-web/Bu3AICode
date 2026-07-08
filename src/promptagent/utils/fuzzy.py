"""Fuzzy Finder。

サブシーケンスマッチによる軽量なあいまい検索を提供する。外部依存を
増やさず、ファイルパス・コマンド・履歴などあらゆる文字列リストに対して
高速に候補を絞り込める。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FuzzyMatch:
    """1件のあいまい検索結果。"""

    candidate: str
    score: float
    matched_indices: list[int]


def fuzzy_score(query: str, candidate: str) -> tuple[float, list[int]] | None:
    """queryがcandidateのサブシーケンスであれば、スコアと一致位置を返す。

    スコアは「連続一致」「先頭一致」「短い文字列」を優先するよう重み付けする。
    一致しない場合はNoneを返す。
    """
    if not query:
        return 0.0, []

    query_lower = query.lower()
    candidate_lower = candidate.lower()

    matched_indices: list[int] = []
    candidate_index = 0
    consecutive_bonus = 0.0
    last_matched_index = -2

    for query_char in query_lower:
        found_index = candidate_lower.find(query_char, candidate_index)
        if found_index == -1:
            return None
        matched_indices.append(found_index)
        if found_index == last_matched_index + 1:
            consecutive_bonus += 1.5
        if found_index == 0:
            consecutive_bonus += 1.0
        last_matched_index = found_index
        candidate_index = found_index + 1

    length_penalty = len(candidate) * 0.01
    score = 10.0 + consecutive_bonus - length_penalty
    return score, matched_indices


def fuzzy_find(query: str, candidates: list[str], limit: int = 20) -> list[FuzzyMatch]:
    """候補群をあいまい検索し、スコアの高い順に上位 `limit` 件を返す。"""
    if not query:
        return [FuzzyMatch(candidate=c, score=0.0, matched_indices=[]) for c in candidates[:limit]]

    matches: list[FuzzyMatch] = []
    for candidate in candidates:
        result = fuzzy_score(query, candidate)
        if result is not None:
            score, indices = result
            matches.append(FuzzyMatch(candidate=candidate, score=score, matched_indices=indices))

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:limit]


def highlight_match(match: FuzzyMatch, *, open_tag: str = "[bold]", close_tag: str = "[/bold]") -> str:
    """一致文字をマークアップで強調した文字列を生成する(Rich向け)。"""
    if not match.matched_indices:
        return match.candidate

    result = []
    matched_set = set(match.matched_indices)
    in_tag = False
    for index, char in enumerate(match.candidate):
        should_highlight = index in matched_set
        if should_highlight and not in_tag:
            result.append(open_tag)
            in_tag = True
        elif not should_highlight and in_tag:
            result.append(close_tag)
            in_tag = False
        result.append(char)
    if in_tag:
        result.append(close_tag)
    return "".join(result)
