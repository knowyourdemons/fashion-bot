"""
Brief card system — three card states + two color themes.

Card states:
  - Weather card (0 real photos): weather + layers + advice + CTA
  - Hybrid card (1-7 real photos): weather strip + items grid + missing + progress
  - Full card (8+ real photos): flat lay with all items

Color themes:
  - "mom" (mom_girl/mom_boy): warm pink palette
  - "woman" (no_kids/pregnant): cool blue palette

Rendering: Jinja2 HTML templates → Playwright (Chrome) → PNG

Main entry: build_brief_card(user, child, outfit, weather, outfit_slots) -> bytes
"""
from __future__ import annotations

import structlog

from services.brief_renderer import (
    get_segment,
    get_segment as _get_segment,  # backward compat for morning_brief imports
    get_theme,
    prepare_weather_data,
    prepare_items_hybrid,
    prepare_items_full,
    prepare_date_context,
    prepare_layers,
    prepare_underwear_line,
    render_template,
    render_html_to_png,
    TYPE_RU,
)
from services.collage_styles import (
    _get_placeholder_label,
    collect_palette as _collect_palette_rich,
)

logger = structlog.get_logger()


# ── Count real photos ────────────────────────────────────────────────────────

def _count_real_photos(outfit_slots: list[dict]) -> int:
    """Count slots with actual photo data."""
    count = 0
    for s in outfit_slots:
        if not s.get("has_item"):
            continue
        if s.get("photo_url") or s.get("photo_id") or s.get("_photo_bytes"):
            count += 1
    return count


# ── Download photos ──────────────────────────────────────────────────────────

async def _get_cached_thumb(item_id: str) -> bytes | None:
    """Check Redis for cached collage thumbnail."""
    if not item_id:
        return None
    try:
        from core.redis import get_redis
        import base64 as _b64
        redis = get_redis()
        raw = await redis.get(f"thumb:{item_id}")
        if raw:
            b64_str = raw.decode() if isinstance(raw, bytes) else raw
            return _b64.b64decode(b64_str)
    except Exception:
        pass
    return None


async def _cache_thumb(item_id: str, thumb_bytes: bytes) -> None:
    """Cache collage thumbnail in Redis (7 day TTL)."""
    if not item_id:
        return
    try:
        from core.redis import get_redis
        import base64 as _b64
        redis = get_redis()
        b64_str = _b64.b64encode(thumb_bytes).decode()
        await redis.set(f"thumb:{item_id}", b64_str, ex=86400 * 7)
    except Exception:
        pass


async def _download_slot_photos(outfit_slots: list[dict]) -> None:
    """Download photos for slots, using cached thumbnails when available.

    Priority:
      1. Redis thumb cache (thumb:{item_id}) — instant, pre-processed
      2. R2 photo_url (bg-removed) → thumbnail pipeline
      3. Telegram photo_id (original) → full pipeline with bg removal
    """
    import httpx
    from services.image_builder import _download_photo

    need_download = [
        s for s in outfit_slots
        if s.get("has_item")
        and not s.get("_photo_bytes")
        and (s.get("photo_id") or s.get("photo_url"))
    ]
    if not need_download:
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        for slot in need_download:
            item_id = slot.get("item_id", "")
            try:
                # 1. Check Redis thumbnail cache
                cached = await _get_cached_thumb(item_id)
                if cached:
                    slot["_photo_bytes"] = cached
                    logger.info("brief_card.thumb_cache_hit", slot=slot.get("slot"))
                    continue

                # 2. Download photo (prefers R2 bg-removed, falls back to Telegram)
                photo_bytes = await _download_photo(
                    client,
                    slot.get("photo_id") or "",
                    slot.get("photo_url"),
                )
                if not photo_bytes:
                    logger.warning("brief_card.photo_empty", slot=slot.get("slot"))
                    continue

                # 3. Bbox crop on ORIGINAL photo (before any transforms)
                _bbox = slot.get("bbox")
                if _bbox and isinstance(_bbox, dict) and _bbox.get("w", 1.0) < 0.95:
                    try:
                        from services.vision import _crop_bbox
                        photo_bytes = _crop_bbox(photo_bytes, _bbox)
                        logger.info("brief_card.bbox_crop", slot=slot.get("slot"))
                    except Exception as _crop_err:
                        logger.warning("brief_card.bbox_crop_failed", error=str(_crop_err))

                # 4. Build thumbnail (EXIF → brightness → rembg → edges → pad → resize)
                from services.image_processor import make_collage_thumbnail_safe
                from PIL import Image
                import io as _io

                # Check if already bg-removed (from R2)
                img_check = Image.open(_io.BytesIO(photo_bytes))
                needs_rembg = img_check.mode not in ("RGBA", "LA", "PA")

                thumb = await make_collage_thumbnail_safe(photo_bytes, needs_bg_removal=needs_rembg)
                slot["_photo_bytes"] = thumb

                # Cache for next time
                await _cache_thumb(item_id, thumb)

                logger.info(
                    "brief_card.thumb_built",
                    slot=slot.get("slot"),
                    size=len(thumb),
                    rembg=needs_rembg,
                )
            except Exception as e:
                logger.warning(
                    "brief_card.photo_failed",
                    slot=slot.get("slot"),
                    error=str(e),
                )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def build_brief_card(
    user,
    child,
    outfit: dict,
    weather: dict,
    outfit_slots: list[dict],
    advice_text: str = "",
    colortype: str = "",
) -> bytes | None:
    """
    Build morning brief card as PNG bytes.

    Chooses card type based on real photo count:
      0 photos  -> weather card (tpl_weather.html)
      1-7       -> hybrid card (tpl_hybrid.html)
      8+        -> full card (tpl_full.html)

    Returns PNG bytes or None on failure.
    """
    segment = get_segment(user)
    theme = get_theme(segment)
    real_photos = _count_real_photos(outfit_slots)

    logger.info(
        "brief_card.build",
        segment=segment,
        real_photos=real_photos,
        total_slots=len(outfit_slots),
    )

    try:
        # Download photos for items that have them but no _photo_bytes yet
        await _download_slot_photos(outfit_slots)
        # Recount after download (some may have failed)
        real_photos = _count_real_photos(outfit_slots)

        # Common data
        date_str, context_str = prepare_date_context(user, child)
        weather_tpl = prepare_weather_data(weather)
        child_name = getattr(child, "name", "") if child else ""
        user_name = getattr(user, "name", "") if user else ""
        name = child_name or user_name or ""

        if real_photos == 0:
            html = _build_weather_html(
                name, context_str, date_str, theme,
                weather_tpl, weather, outfit_slots, advice_text,
            )
        elif real_photos < 8:
            html = _build_hybrid_html(
                name, context_str, date_str, theme, segment,
                weather_tpl, outfit_slots, outfit, advice_text,
                real_photos, colortype,
            )
        else:
            html = _build_full_html(
                name, context_str, date_str, theme,
                weather_tpl, outfit_slots, outfit, advice_text,
                colortype,
            )

        png_bytes = await render_html_to_png(html)
        if png_bytes:
            card_type = (
                "weather" if real_photos == 0
                else "hybrid" if real_photos < 8
                else "full"
            )
            logger.info("brief_card.rendered", size=len(png_bytes), card_type=card_type)
            return png_bytes

        logger.warning("brief_card.render_failed")
        return None

    except Exception as e:
        logger.warning("brief_card.build_failed", error=str(e), exc_info=True)
        return None


# ── Weather card (0 photos) ──────────────────────────────────────────────────

def _build_weather_html(
    name: str, context_str: str, date_str: str, theme: dict,
    weather_tpl: dict, weather_raw: dict, outfit_slots: list[dict],
    advice_text: str,
) -> str:
    layers = prepare_layers(weather_raw, outfit_slots)

    return render_template(
        "tpl_weather.html",
        css_class=theme["css_class"],
        name=name,
        context=context_str,
        date_str=date_str,
        weather=weather_tpl,
        layers=layers,
        kassi_comment=advice_text,
    )


# ── Hybrid card (1-7 photos) ────────────────────────────────────────────────

def _build_hybrid_html(
    name: str, context_str: str, date_str: str, theme: dict,
    segment: str, weather_tpl: dict, outfit_slots: list[dict],
    outfit: dict, advice_text: str, real_photo_count: int,
    colortype: str = "",
) -> str:
    items, missing = prepare_items_hybrid(outfit_slots)
    palette = _collect_palette_rich(outfit_slots, colortype=colortype)
    base_layer = prepare_underwear_line(outfit)

    # Progress
    threshold = 8 if segment == "mom" else 12
    progress_pct = min(100, int(real_photo_count / max(threshold, 1) * 100))
    next_item_ru = missing[0]["name_ru"] if missing else "вещь"
    progress_text = f"{real_photo_count}/{threshold} · 📸 Сфоткай {next_item_ru.lower()}!"

    return render_template(
        "tpl_hybrid.html",
        css_class=theme["css_class"],
        name=name,
        context=context_str,
        date_str=date_str,
        weather=weather_tpl,
        items=items,
        missing=missing,
        palette=palette,
        base_layer=base_layer,
        kassi_comment=advice_text,
        progress_pct=progress_pct,
        progress_text=progress_text,
    )


# ── Full card (8+ photos) ───────────────────────────────────────────────────

def _build_full_html(
    name: str, context_str: str, date_str: str, theme: dict,
    weather_tpl: dict, outfit_slots: list[dict], outfit: dict,
    advice_text: str, colortype: str = "",
) -> str:
    items = prepare_items_full(outfit_slots)
    palette = _collect_palette_rich(outfit_slots, colortype=colortype)
    base_layer = prepare_underwear_line(outfit)

    return render_template(
        "tpl_full.html",
        css_class=theme["css_class"],
        name=name,
        context=context_str,
        date_str=date_str,
        weather=weather_tpl,
        items=items,
        palette=palette,
        base_layer=base_layer,
        kassi_comment=advice_text,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MORNING UPDATE CARD
# ══════════════════════════════════════════════════════════════════════════════

async def build_morning_update(
    user,
    child,
    evening_slots: list[dict],
    weather_now: dict,
    weather_changed: bool,
    change_text: str,
    kassi_comment: str,
) -> bytes | None:
    """Render morning update card (weather changed / not changed)."""
    segment = get_segment(user)
    theme = get_theme(segment)
    date_str, context_str = prepare_date_context(user, child)

    child_name = getattr(child, "name", "") if child else ""
    user_name = getattr(user, "name", "") if user else ""
    name = child_name or user_name or ""

    from services.brief_renderer import prepare_items_morning
    items = prepare_items_morning(evening_slots)

    # Weather now for header
    from services.brief_renderer import format_temp
    from services.brief_weather import wmo_to_emoji
    temp_now = weather_now.get("temp_now") or weather_now.get("temp_morning")
    wmo_now = weather_now.get("wmo_morning", 0)
    weather_now_tpl = {}
    if temp_now is not None:
        weather_now_tpl = {
            "icon": wmo_to_emoji(wmo_now),
            "temp_str": format_temp(temp_now),
            "is_good": not weather_changed,
        }

    html = render_template(
        "tpl_morning.html",
        css_class=theme["css_class"],
        name=name,
        context=context_str,
        date_str=date_str,
        weather_now=weather_now_tpl,
        changed=weather_changed,
        change_text=change_text,
        items=items,
        kassi_comment=kassi_comment,
    )

    try:
        png = await render_html_to_png(html)
        if png:
            logger.info("morning_update.rendered", size=len(png))
        return png
    except Exception as e:
        logger.warning("morning_update.failed", error=str(e))
        return None


# ══════════════════════════════════════════════════════════════════════════════
# BUTTON LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def get_brief_buttons(
    segment: str,
    real_photo_count: int,
    brief_id: str,
    first_missing_slot: str = "",
) -> dict:
    """
    Return inline_keyboard dict for the brief card.

    Rules:
      0 photos:           [Сфоткать] [Потом]
      1-7 photos mom:     [Надели] [Переодень] + specific missing item CTA
      8+ photos mom:      [Надели] [Переодень] [Переслать]
      woman with outfit:  [Нравится] [Другой вариант] [Stories]
      woman advice only:  [Спасибо] [Ещё совет]
    """
    if real_photo_count == 0:
        return {
            "inline_keyboard": [[
                {"text": "📸 Сфоткать", "callback_data": "add_items_hint"},
                {"text": "Потом", "callback_data": f"brief_feedback:later:{brief_id}"},
            ]]
        }

    if segment == "mom":
        if real_photo_count >= 8:
            return {
                "inline_keyboard": [
                    [
                        {"text": "👍 Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
                        {"text": "🔄 Другой", "callback_data": f"reroll:{brief_id}"},
                        {"text": "📤 Переслать", "callback_data": f"share:{brief_id}"},
                    ],
                ]
            }
        else:
            # 1-7 photos mom — no 3rd button, CTA is in progress bar
            return {
                "inline_keyboard": [[
                    {"text": "👍 Надели", "callback_data": f"brief_feedback:up:{brief_id}"},
                    {"text": "🔄 Другой", "callback_data": f"reroll:{brief_id}"},
                ]]
            }

    # segment == "woman"
    if real_photo_count >= 8:
        return {
            "inline_keyboard": [[
                {"text": "👍 Нравится", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "🔄 Другой", "callback_data": f"reroll:{brief_id}"},
                {"text": "📤 Подругу", "callback_data": f"ask_friend:{brief_id}"},
            ]]
        }
    elif real_photo_count > 0:
        return {
            "inline_keyboard": [[
                {"text": "👍 Нравится", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "🔄 Другой", "callback_data": f"reroll:{brief_id}"},
            ]]
        }
    else:
        return {
            "inline_keyboard": [[
                {"text": "Спасибо", "callback_data": f"brief_feedback:up:{brief_id}"},
                {"text": "Ещё совет", "callback_data": "reroll_advice"},
            ]]
        }
