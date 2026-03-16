"""Tests for permissions."""
import pytest
from exceptions import PermissionDeniedError, WardrobeFullError
from core.permissions import check_feature, check_wardrobe_limit, get_daily_limit


def test_free_plan_no_brief():
    with pytest.raises(PermissionDeniedError):
        check_feature("free", "morning_brief")


def test_basic_plan_has_brief():
    check_feature("basic", "morning_brief")  # no exception


def test_wardrobe_limit_exceeded():
    with pytest.raises(WardrobeFullError):
        check_wardrobe_limit("free", 20)


def test_wardrobe_limit_ok():
    check_wardrobe_limit("free", 19)  # no exception


def test_premium_unlimited():
    assert get_daily_limit("premium") == -1
