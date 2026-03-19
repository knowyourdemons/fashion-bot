"""Тесты: _warm_outfit_comment генерирует правильные комментарии."""


class TestWarmOutfitComment:

    def _get_comment(self, score, name="Алиса", temp=6.0, has_ow=True, missing=None):
        from bot.handlers.wardrobe import _warm_outfit_comment
        return _warm_outfit_comment(score, name, temp, has_ow, missing)

    def test_high_score_no_выбор(self):
        """Комментарий НЕ содержит 'выбор' (Касси собрала, не мама)."""
        comment = self._get_comment(9.0)
        assert "выбор" not in comment.lower()

    def test_medium_score_no_выбор(self):
        comment = self._get_comment(7.5)
        assert "выбор" not in comment.lower()

    def test_low_score_no_выбор(self):
        comment = self._get_comment(5.5)
        assert "выбор" not in comment.lower()

    def test_contains_child_name(self):
        comment = self._get_comment(8.0, name="Матвей")
        assert "Матвей" in comment

    def test_missing_slots_adds_tip(self):
        comment = self._get_comment(7.0, missing=["outerwear", "footwear"])
        assert "куртку" in comment.lower() or "обувь" in comment.lower()

    def test_no_missing_no_tip(self):
        comment = self._get_comment(9.0, missing=None)
        assert "добавь" not in comment.lower() or "Совет" not in comment

    def test_returns_string(self):
        comment = self._get_comment(7.0)
        assert isinstance(comment, str)
        assert len(comment) > 10
