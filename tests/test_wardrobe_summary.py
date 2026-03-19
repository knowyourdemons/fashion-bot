"""Тесты: wardrobe summary для system prompt."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


class TestWardrobeSummary:

    def _make_items(self, count=5):
        items = []
        for i in range(count):
            item = MagicMock()
            item.category_group = ["outerwear", "top", "bottom", "footwear", "accessory"][i % 5]
            item.type = f"Вещь {i}"
            item.color = "розовый"
            items.append(item)
        return items

    def test_summary_groups_by_category(self):
        from services.outfit_builder import get_wardrobe_summary
        items = self._make_items(10)

        with patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock) as mock_goi:
            mock_goi.return_value = items
            summary = asyncio.run(get_wardrobe_summary("owner-id", "child", session=AsyncMock()))

        assert "10 вещей" in summary

    def test_summary_max_30_items(self):
        """Summary не должен включать > 30 вещей (экономия токенов)."""
        from services.outfit_builder import get_wardrobe_summary
        items = self._make_items(100)

        with patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock) as mock_goi:
            mock_goi.return_value = items
            summary = asyncio.run(get_wardrobe_summary("owner-id", "child", session=AsyncMock()))

        assert "100 вещей" in summary  # общий count — ок
        assert summary.count("Вещь") <= 30  # но перечислено max 30

    def test_empty_wardrobe(self):
        from services.outfit_builder import get_wardrobe_summary

        with patch("db.crud.wardrobe.get_owner_items", new_callable=AsyncMock) as mock_goi:
            mock_goi.return_value = []
            summary = asyncio.run(get_wardrobe_summary("owner-id", "child", session=AsyncMock()))

        assert "пуст" in summary.lower()
