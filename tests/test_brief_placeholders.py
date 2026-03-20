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


def test_all_items_in_dressing_order():
    """Утренний бриф = текст, все вещи показываются в порядке одевания."""
    outfit = _base_outfit(
        top=FakeItem(type="кофта", color="синий"),
        bottom=FakeItem(type="штаны", color="серый"),
        tights=FakeItem(type="колготки", color="белый"),
        outerwear=FakeItem(type="куртка", color="чёрный"),
        footwear=FakeItem(type="ботинки", color="коричневый"),
    )
    result = _format_child_block("Алиса", "садик", outfit, temp=8.0)
    # Все вещи должны быть в тексте (бриф = текст без коллажа)
    assert "кофта" in result, f"FAIL: кофта должна быть в тексте\n{result}"
    assert "штаны" in result, f"FAIL: штаны должны быть в тексте\n{result}"
    assert "куртка" in result, f"FAIL: куртка должна быть в тексте\n{result}"
    assert "ботинки" in result, f"FAIL: ботинки должны быть в тексте\n{result}"
    # Невидимые тоже
    assert "трусики" in result
    assert "колготки" in result
    # Порядок: ПОД ОДЕЖДУ → ОДЕЖДА → ОБУВЬ → НА ВЫХОД
    idx_under = result.index("ПОД ОДЕЖДУ")
    idx_clothes = result.index("ОДЕЖДА")
    idx_shoes = result.index("ОБУВЬ")
    idx_exit = result.index("НА ВЫХОД")
    assert idx_under < idx_clothes < idx_shoes < idx_exit
    print("PASS: все вещи в порядке одевания")


if __name__ == "__main__":
    test_underwear_text_shown()
    test_no_placeholder_when_warm()
    test_all_items_in_dressing_order()
    print("Все тесты PASS")
