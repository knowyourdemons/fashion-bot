import sys
sys.path.insert(0, "/app")

class FakeItem:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

from worker.tasks.morning_brief import _format_child_block

def test_placeholder_outerwear():
    outfit = {
        "thermal_top": None, "thermal_bottom": None,
        "underwear_items": [], "underwear_text": "трусики",
        "one_piece": None,
        "top": FakeItem(type="свитер", color="серый"),
        "bottom": FakeItem(type="штаны", color="розовый"),
        "removable_layer": None,
        "tights": FakeItem(type="колготки", color="бежевый"),
        "socks": None,
        "footwear": FakeItem(type="ботинки", color="синий"),
        "outerwear": None,
        "hat": None, "scarf": None, "gloves": None,
        "warnings": [], "all_items": [],
    }
    result = _format_child_block("Алиса", "садик", outfit, 7.5, temp=3.0)
    assert "(нет в гардеробе)" in result, f"FAIL: нет placeholder\n{result}"
    assert "куртк" in result or "ветровк" in result or "пуховик" in result, \
        f"FAIL: нет упоминания куртки\n{result}"
    print("PASS: placeholder для outerwear при +3°C")

def test_no_placeholder_when_warm():
    outfit = {
        "thermal_top": None, "thermal_bottom": None,
        "underwear_items": [], "underwear_text": "трусики",
        "one_piece": None,
        "top": FakeItem(type="футболка", color="белый"),
        "bottom": FakeItem(type="шорты", color="розовый"),
        "removable_layer": None, "tights": None, "socks": None,
        "footwear": FakeItem(type="сандалии", color="белый"),
        "outerwear": None,
        "hat": None, "scarf": None, "gloves": None,
        "warnings": [], "all_items": [],
    }
    result = _format_child_block("Алиса", "садик", outfit, 6.5, temp=20.0)
    assert "куртк" not in result, \
        f"FAIL: при +20°C не должно быть куртки\n{result}"
    print("PASS: нет placeholder для outerwear при +20°C")

def test_placeholder_footwear():
    outfit = {
        "thermal_top": None, "thermal_bottom": None,
        "underwear_items": [], "underwear_text": "трусики",
        "one_piece": None,
        "top": FakeItem(type="кофта", color="синий"),
        "bottom": FakeItem(type="штаны", color="серый"),
        "removable_layer": None,
        "tights": FakeItem(type="колготки", color="белый"),
        "socks": None,
        "footwear": None,
        "outerwear": FakeItem(type="куртка", color="чёрный"),
        "hat": None, "scarf": None, "gloves": None,
        "warnings": [], "all_items": [],
    }
    result = _format_child_block("Алиса", "садик", outfit, 7.0, temp=8.0)
    assert "обувь" in result.lower(), \
        f"FAIL: нет placeholder для обуви\n{result}"
    assert "(нет в гардеробе)" in result, f"FAIL: нет '(нет в гардеробе)'\n{result}"
    print("PASS: placeholder для footwear")

if __name__ == "__main__":
    test_placeholder_outerwear()
    test_no_placeholder_when_warm()
    test_placeholder_footwear()
    print("Все тесты PASS")
