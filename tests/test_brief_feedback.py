"""Тесты: brief feedback handlers."""
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch


class TestBriefFeedback:

    def _make_update(self, data="brief_feedback:up:550e8400-e29b-41d4-a716-446655440000"):
        update = MagicMock()
        update.callback_query = AsyncMock()
        update.callback_query.data = data
        update.callback_query.answer = AsyncMock()
        update.callback_query.message = AsyncMock()
        update.callback_query.edit_message_reply_markup = AsyncMock()
        return update

    def _make_session_mock(self, mock_session_cls):
        """Setup AsyncWriteSession as a proper async context manager."""
        inner = AsyncMock()
        inner.commit = AsyncMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=inner)
        ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = ctx
        return inner

    @pytest.mark.asyncio
    @patch("bot.handlers.brief.AsyncWriteSession")
    @patch("bot.handlers.brief.get_log", new_callable=AsyncMock)
    @patch("bot.handlers.brief.update_feedback", new_callable=AsyncMock)
    @patch("bot.handlers.brief.update_wear_count", new_callable=AsyncMock)
    async def test_up_updates_wear_count(self, mock_wear, mock_fb, mock_log, mock_session):
        """'Надели' → update_wear_count вызывается."""
        from bot.handlers.brief import handle_brief_feedback

        self._make_session_mock(mock_session)
        mock_log.return_value = MagicMock(outfit_items=["550e8400-e29b-41d4-a716-446655440001"])
        update = self._make_update("brief_feedback:up:550e8400-e29b-41d4-a716-446655440000")
        context = MagicMock()

        await handle_brief_feedback(update, context)

        mock_wear.assert_called_once()

    @pytest.mark.asyncio
    @patch("bot.handlers.brief.AsyncWriteSession")
    @patch("bot.handlers.brief.get_log", new_callable=AsyncMock)
    @patch("bot.handlers.brief.update_feedback", new_callable=AsyncMock)
    async def test_down_shows_reroll_button(self, mock_fb, mock_log, mock_session):
        """'Другое' → ответ содержит inline кнопку."""
        from bot.handlers.brief import handle_brief_feedback

        self._make_session_mock(mock_session)
        mock_log.return_value = MagicMock(outfit_items=[])
        update = self._make_update("brief_feedback:down:550e8400-e29b-41d4-a716-446655440000")
        context = MagicMock()

        await handle_brief_feedback(update, context)

        # Split delivery: buttons on text message, so edit_message_text
        call_args = update.callback_query.edit_message_text.call_args
        assert call_args is not None
        assert "reply_markup" in call_args.kwargs
