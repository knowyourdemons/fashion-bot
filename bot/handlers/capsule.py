"""Capsule handler — seasonal capsule builder UI."""
import structlog
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from core.permissions import get_effective_plan
from services.i18n import t, get_user_lang

logger = structlog.get_logger()

# Color name → hex for palette dots
_COLOR_HEX = {
    "чёрный": "#2C2C2C", "белый": "#F5F5F5", "серый": "#9E9E9E",
    "тёмно-серый": "#616161", "светло-серый": "#BDBDBD",
    "бежевый": "#D4C5A9", "коричневый": "#795548", "тёмно-коричневый": "#4E342E",
    "синий": "#1565C0", "тёмно-синий": "#1A237E", "голубой": "#64B5F6",
    "красный": "#D32F2F", "бордовый": "#7B1FA2", "розовый": "#F48FB1",
    "зелёный": "#388E3C", "тёмно-зелёный": "#1B5E20", "хаки": "#827717",
    "жёлтый": "#FDD835", "оранжевый": "#F57C00", "фиолетовый": "#7B1FA2",
    "бирюзовый": "#00897B", "кремовый": "#FFF8E1", "молочный": "#FFFDE7",
}

_SEASON_NAMES = {"spring": "Весна", "summer": "Лето", "autumn": "Осень", "winter": "Зима"}
_SEASON_NAMES_EN = {"spring": "Spring", "summer": "Summer", "autumn": "Autumn", "winter": "Winter"}


async def handle_capsule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command /capsule or callback capsule:build → build seasonal capsule."""
    user = context.user_data.get("db_user")
    if not user:
        return

    # Determine source: command or callback
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id
        reply_func = query.message.reply_photo
    else:
        chat_id = update.effective_chat.id
        reply_func = update.message.reply_photo

    lang = get_user_lang(user)
    plan = get_effective_plan(user)

    # Premium gate
    if plan not in ("premium", "ultra", "admin"):
        text = t("capsule.premium_gate", lang)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
        ]])
        if update.callback_query:
            await update.callback_query.message.reply_text(text, reply_markup=kb)
        else:
            await update.message.reply_text(text, reply_markup=kb)
        return

    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    try:
        from db.base import AsyncReadSession
        from db.crud.wardrobe import get_owner_items
        from services.wardrobe_math import build_seasonal_capsule
        from services.brief_renderer import render_template, render_html_to_png

        async with AsyncReadSession() as session:
            items = await get_owner_items(session, user.id, "user")

        from core.permissions import MIN_ITEMS_GAP_ANALYSIS
        if len(items) < MIN_ITEMS_GAP_ANALYSIS:
            text = t("capsule.too_few", lang, min=str(MIN_ITEMS_GAP_ANALYSIS))
            if update.callback_query:
                await update.callback_query.message.reply_text(text)
            else:
                await update.message.reply_text(text)
            return

        capsule = build_seasonal_capsule(items)
        season = capsule["season"]
        season_name = (_SEASON_NAMES_EN if lang == "en" else _SEASON_NAMES).get(season, season)

        # Convert color names to hex for template
        palette_hex = []
        for color_name in capsule["palette_colors"][:6]:
            hex_val = _COLOR_HEX.get(color_name, "#BDBDBD")
            palette_hex.append(hex_val)

        html = render_template(
            "tpl_capsule_card.html",
            name=user.name or t("capsule.your", lang),
            season_name=season_name,
            item_count=len(capsule["items"]),
            total_combos=capsule["total_combos"],
            palette=palette_hex,
        )
        png = await render_html_to_png(html, width=440)

        if not png:
            # Fallback: text only
            await _send_text_capsule(update, capsule, season_name, lang)
            return

        caption = t("capsule.result", lang,
                     season=season_name,
                     count=len(capsule["items"]),
                     combos=capsule["total_combos"])

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                t("capsule.share_btn", lang), callback_data="capsule:share"
            ),
            InlineKeyboardButton(
                t("capsule.ok_btn", lang), callback_data="capsule:ok"
            ),
        ]])

        await reply_func(photo=png, caption=caption, reply_markup=kb)
        logger.info("capsule.built", user_id=str(user.id), items=len(capsule["items"]),
                     combos=capsule["total_combos"])

    except Exception as e:
        logger.error("capsule.error", user_id=str(user.id), error=str(e))
        text = t("error.generic", lang)
        if update.callback_query:
            await update.callback_query.message.reply_text(text)
        else:
            await update.message.reply_text(text)


async def _send_text_capsule(update, capsule, season_name, lang):
    """Fallback when renderer is unavailable."""
    items = capsule["items"]
    lines = [f"👗 {t('capsule.title', lang)} {season_name}\n"]
    for item in items[:15]:
        color = getattr(item, "color", "") or ""
        itype = getattr(item, "type", "") or ""
        lines.append(f"  • {color} {itype}".strip())
    if len(items) > 15:
        lines.append(f"  ... +{len(items) - 15}")
    lines.append(f"\n📊 {len(items)} → {capsule['total_combos']} {t('capsule.combos_word', lang)}")

    text = "\n".join(lines)
    if update.callback_query:
        await update.callback_query.message.reply_text(text)
    else:
        await update.message.reply_text(text)


async def handle_capsule_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: capsule:ok → dismiss."""
    await update.callback_query.answer(t("capsule.thanks", get_user_lang(context.user_data.get("db_user"))))
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def handle_capsule_share(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback: capsule:share → forward hint."""
    await update.callback_query.answer()
    lang = get_user_lang(context.user_data.get("db_user"))
    await update.callback_query.message.reply_text(t("capsule.share_hint", lang))
