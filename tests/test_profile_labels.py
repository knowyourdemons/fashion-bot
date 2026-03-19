"""Тесты: profile segment labels."""


class TestProfileLabels:

    def test_mom_girl_label(self):
        from bot.handlers.profile import _SEGMENT_LABELS
        label = _SEGMENT_LABELS.get("mom_girl", "")
        assert "дочка" in label.lower() or "👧" in label

    def test_mom_boy_label(self):
        from bot.handlers.profile import _SEGMENT_LABELS
        label = _SEGMENT_LABELS.get("mom_boy", "")
        assert "сын" in label.lower() or "👦" in label

    def test_no_segment_word(self):
        """Ни один label не содержит слово 'Сегмент' или 'Мама девочки'."""
        from bot.handlers.profile import _SEGMENT_LABELS
        for key, label in _SEGMENT_LABELS.items():
            assert "Сегмент" not in label
            assert "Мама девочки" not in label
            assert "Мама мальчика" not in label
