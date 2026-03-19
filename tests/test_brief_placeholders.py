import sys
sys.path.insert(0, "/app")

class FakeItem:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

from worker.tasks.morning_brief import _format_child_block


def _base_outfit(**overrides):
    outfit = {
        "thermal_top": None, "thermal_bottom": None,
        "underwear_items": [], "underwear_text": "трусики",
        "one_piece": None,
        "top": None, "bottom": None,
        "removable_layer": None, "tights": None, "socks": None,
        "footwear": None, "outerwear": None,
        "hat": None, "scarf": None, "gloves": None,
        "warnings": [], "all_items": [],
    }
    outfit.update(overrides)
    return outfit


def test_underwear_text_shown():
    """Бельё (невидимые вещи) показывается одной строкой."""
    outfit = _base_outfit(
        top=FakeItem(type="свитер", color="серый"),
        bottom=FakeItem(type="штаны", color="розовый"),
        tights=FakeItem(type="колготки", color="бежевый"),
        footwear=FakeItem(type="ботинки", color="синий"),
    )
    result = _format_child_block("Алиса", "садик", outfit, temp=3.0)
    assert "Алиса" in result
    assert "садик" in result
    assert "трусики" in result  # underwear_text должен быть
    assert "колготки" in result  # носки/колготки тоже невидимые
    print("PASS: underwear_text и колготки отображаются")


def test_no_placeholder_when_warm():
    """При тепле нет упоминания куртки в тексте (она на коллаже)."""
    outfit = _base_outfit(
        top=FakeItem(type="футболка", color="белый"),
        bottom=FakeItem(type="шорты", color="розовый"),
        footwear=FakeItem(type="сандалии", color="белый"),
    )
    result = _format_child_block("Алиса", "садик", outfit, temp=20.0)
    assert "куртк" not in result, \
        f"FAIL: при +20°C не должно быть куртки в тексте\n{result}"
    print("PASS: нет упоминания куртки при +20°C")


def test_visible_items_not_in_text():
    """Видимые вещи (top/bottom/outerwear/footwear) НЕ дублируются в тексте."""
    outfit = _base_outfit(
        top=FakeItem(type="кофта", color="синий"),
        bottom=FakeItem(type="штаны", color="серый"),
        tights=FakeItem(type="колготки", color="белый"),
        outerwear=FakeItem(type="куртка", color="чёрный"),
        footwear=FakeItem(type="ботинки", color="коричневый"),
    )
    result = _format_child_block("Алиса", "садик", outfit, temp=8.0)
    # Видимые вещи НЕ должны быть в тексте
    assert "кофта" not in result, f"FAIL: кофта (top) не должна быть в тексте\n{result}"
    assert "штаны" not in result, f"FAIL: штаны (bottom) не должны быть в тексте\n{result}"
    assert "куртка" not in result, f"FAIL: куртка (outerwear) не должна быть в тексте\n{result}"
    assert "ботинки" not in result, f"FAIL: ботинки (footwear) не должны быть в тексте\n{result}"
    # Но невидимые должны быть
    assert "трусики" in result
    assert "колготки" in result
    print("PASS: видимые вещи не дублируются, невидимые отображаются")


if __name__ == "__main__":
    test_underwear_text_shown()
    test_no_placeholder_when_warm()
    test_visible_items_not_in_text()
    print("Все тесты PASS")
