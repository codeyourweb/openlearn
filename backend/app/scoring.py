# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Scoring rules.

A question is correct only when the participant selected *exactly* the set of
correct options (OWASP-safe: grading always happens server side, never in the
browser).
"""

from __future__ import annotations

from collections.abc import Iterable


def is_answer_correct(selected: Iterable[int], correct: Iterable[int]) -> bool:
    selected_set = set(selected)
    correct_set = set(correct)
    if not correct_set:
        return False
    return selected_set == correct_set


def points_for(correct: bool, points: int, wrong_answer_policy: str) -> int:
    if correct:
        return points
    if wrong_answer_policy == "penalty":
        return -points
    return 0


def clamp_score(score: int) -> int:
    """Scores may go negative with the penalty policy; that is intended."""
    return score
