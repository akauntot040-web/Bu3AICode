"""Fuzzy Finderの単体テスト。"""

from __future__ import annotations

from promptagent.utils.fuzzy import fuzzy_find, fuzzy_score


def test_fuzzy_score_matches_subsequence() -> None:
    result = fuzzy_score("mn", "main.py")
    assert result is not None
    score, indices = result
    assert indices == [0, 3]


def test_fuzzy_score_returns_none_when_not_subsequence() -> None:
    assert fuzzy_score("xyz", "main.py") is None


def test_fuzzy_find_ranks_prefix_match_higher() -> None:
    candidates = ["src/utils/main.py", "main.py", "domain.py"]
    matches = fuzzy_find("main", candidates)
    assert matches[0].candidate == "main.py"


def test_fuzzy_find_empty_query_returns_all() -> None:
    candidates = ["a.py", "b.py"]
    matches = fuzzy_find("", candidates)
    assert [m.candidate for m in matches] == candidates
