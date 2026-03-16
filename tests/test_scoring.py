"""Tests for scoring service."""
import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from services.scoring import ScoringService
from db.models.scoring_matrix import ScoringMatrix


def make_matrix(criteria, max_score):
    m = ScoringMatrix()
    m.criteria = criteria
    m.max_score = max_score
    m.version = "v1.0"
    return m


def test_score_item_full_score():
    svc = ScoringService(MagicMock(), MagicMock())
    matrix = make_matrix({"comfort": 3, "practicality": 2}, max_score=5)
    score, breakdown = svc.score_item({"comfort": 3, "practicality": 2}, matrix)
    assert score == Decimal("10.00")


def test_score_item_zero():
    svc = ScoringService(MagicMock(), MagicMock())
    matrix = make_matrix({"comfort": 3}, max_score=3)
    score, _ = svc.score_item({}, matrix)
    assert score == Decimal("0.00")


def test_score_outfit_wow():
    svc = ScoringService(MagicMock(), MagicMock())
    criteria = {"transformation": 3, "unexpected_combination": 2, "color_harmony": 2}
    _, _, is_wow = svc.score_outfit(criteria, is_child=False)
    assert is_wow is True


def test_score_outfit_not_wow():
    svc = ScoringService(MagicMock(), MagicMock())
    _, _, is_wow = svc.score_outfit({}, is_child=False)
    assert is_wow is False
