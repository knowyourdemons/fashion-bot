"""Тесты: color_circle маппинг."""


class TestColorCircle:

    def test_pink(self):
        from services.outfit_builder import color_circle
        assert color_circle("розовый") == "🟣"

    def test_blue(self):
        from services.outfit_builder import color_circle
        assert color_circle("синий") == "🔵"

    def test_white(self):
        from services.outfit_builder import color_circle
        assert color_circle("белый") == "⚪"

    def test_black(self):
        from services.outfit_builder import color_circle
        assert color_circle("чёрный") == "⚫"

    def test_beige(self):
        from services.outfit_builder import color_circle
        assert color_circle("бежевый") == "🟡"

    def test_compound_color(self):
        from services.outfit_builder import color_circle
        assert color_circle("пыльно-розовый") == "🟣"

    def test_none_returns_white(self):
        from services.outfit_builder import color_circle
        assert color_circle(None) == "⚪"

    def test_empty_returns_white(self):
        from services.outfit_builder import color_circle
        assert color_circle("") == "⚪"

    def test_unknown_color(self):
        from services.outfit_builder import color_circle
        assert color_circle("перламутровый") == "⚪"
