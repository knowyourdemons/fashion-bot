"""Monthly report — 1-е число, push карточка premium юзерам, тизер free."""
import asyncio
from datetime import date, timedelta

import pytz
import structlog

from config import settings

logger = structlog.get_logger()

_MONTH_NAMES_RU = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
}
_MONTH_NAMES_EN = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

# Color name → hex for template
_COLOR_HEX = {
    "чёрный": "#2C2C2C", "белый": "#F5F5F5", "серый": "#9E9E9E",
    "бежевый": "#D4C5A9", "синий": "#1565C0", "голубой": "#64B5F6",
    "красный": "#D32F2F", "розовый": "#F48FB1", "зелёный": "#388E3C",
    "коричневый": "#795548", "бордовый": "#7B1FA2", "хаки": "#827717",
}


async def run() -> None:
    """Cron trigger — runs daily 08:00 UTC, sends on 1st of month."""
    today = date.today()
    if today.day != 1:
        logger.info("analytics_report.skip", day=today.day)
        return

    logger.info("analytics_report.start")

    from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    from sqlalchemy import select, or_
    from datetime import datetime, timezone as _tz

    from db.base import AsyncReadSession
    from db.models.user import User
    from db.crud.wardrobe import get_owner_items
    from services.wardrobe_math import build_monthly_report
    from services.brief_renderer import render_template, render_html_to_png
    from core.permissions import get_effective_plan
    from services.i18n import t, get_user_lang

    bot = Bot(token=settings.telegram_bot_token)
    sent = 0
    teaser_sent = 0

    try:
        # Premium users — full report
        async with AsyncReadSession() as session:
            result = await session.execute(
                select(User).where(
                    User.onboarding_completed.is_(True),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
            all_users = list(result.scalars().all())

        prev_month = today.month - 1 or 12
        month_names_ru = _MONTH_NAMES_RU
        month_names_en = _MONTH_NAMES_EN

        for user in all_users:
            try:
                plan = get_effective_plan(user)
                lang = get_user_lang(user)
                month_names = month_names_en if lang == "en" else month_names_ru
                month_name = month_names.get(prev_month, "")

                if plan in ("premium", "ultra", "admin"):
                    # Full report
                    async with AsyncReadSession() as session:
                        items = await get_owner_items(session, user.id, "user")

                    if not items:
                        continue

                    report = await build_monthly_report(user.id, items, prev_month)

                    # Prepare top_colors for template
                    top_colors = []
                    total_wears = sum(cnt for _, cnt in report["top_colors"]) or 1
                    for color, cnt in report["top_colors"]:
                        top_colors.append({
                            "color": color,
                            "pct": int(cnt / total_wears * 100),
                            "hex": _COLOR_HEX.get(color, "#BDBDBD"),
                        })

                    html = render_template(
                        "tpl_monthly_report.html",
                        name=user.name or "Style",
                        month_name=month_name,
                        total_outfits=report["total_outfits"],
                        usage_pct=report["usage_pct"],
                        prev_usage_pct=None,
                        wardrobe_size=report["wardrobe_size"],
                        unique_items=report["unique_items_used"],
                        top_colors=top_colors,
                        forgotten_count=report["forgotten_count"],
                        estimated_savings=report["estimated_savings"],
                        co2_saved=report["co2_saved"],
                        total_combos=report["total_combos"],
                    )
                    png = await render_html_to_png(html, width=440)

                    caption = t("report.caption", lang,
                                month=month_name,
                                outfits=report["total_outfits"],
                                used=report["unique_items_used"],
                                pct=report["usage_pct"],
                                savings=report["estimated_savings"])

                    kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            t("report.share_btn", lang),
                            callback_data="report:share",
                        ),
                        InlineKeyboardButton(
                            t("report.ok_btn", lang),
                            callback_data="report:ok",
                        ),
                    ]])

                    if png:
                        await bot.send_photo(
                            chat_id=user.telegram_id,
                            photo=png,
                            caption=caption,
                            reply_markup=kb,
                        )
                    else:
                        await bot.send_message(
                            chat_id=user.telegram_id,
                            text=caption,
                            reply_markup=kb,
                        )
                    sent += 1

                else:
                    # Free user teaser
                    await bot.send_message(
                        chat_id=user.telegram_id,
                        text=t("report.teaser", lang),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("✨ Premium", callback_data="show_upgrade"),
                        ]]),
                    )
                    teaser_sent += 1

                await asyncio.sleep(1)  # Telegram rate limit

            except Exception as e:
                logger.warning("analytics_report.user_error",
                               user_id=str(user.id), error=str(e))

    except Exception as e:
        logger.error("analytics_report.error", error=str(e))

    logger.info("analytics_report.done", sent=sent, teaser_sent=teaser_sent)
