"""
Brief card system — unified flat-lay layout + two color themes.

All card states use tpl_flatlay.html:
  - 0 real photos: flat-lay with all placeholder slots
  - 1+ real photos: flat-lay with real photos + placeholders for missing
  - Morning update: flat-lay with alert banner (weather changed / OK)

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
    prepare_items_hybrid,  # legacy — kept for backward compat imports
    prepare_items_full,    # legacy — kept for backward compat imports
    prepare_date_context,
    prepare_layers,        # legacy — kept for backward compat imports
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

                # 4. Build thumbnail
                from PIL import Image
                import io as _io

                # Check if already bg-removed (from R2)
                img_check = Image.open(_io.BytesIO(photo_bytes))
                needs_rembg = img_check.mode not in ("RGBA", "LA", "PA")

                if needs_rembg:
                    # No R2 — full pipeline (Telegram photo)
                    from services.image_processor import make_collage_thumbnail_safe
                    thumb = await make_collage_thumbnail_safe(photo_bytes, needs_bg_removal=True)
                else:
                    # R2 RGBA with original colors — trim + resize (no rembg needed)
                    from services.image_processor import soften_edges
                    img_rgba = img_check.convert("RGBA")

                    _alpha_bbox = img_rgba.split()[3].getbbox()
                    if _alpha_bbox:
                        _p = 5
                        _alpha_bbox = (
                            max(0, _alpha_bbox[0] - _p),
                            max(0, _alpha_bbox[1] - _p),
                            min(img_rgba.size[0], _alpha_bbox[2] + _p),
                            min(img_rgba.size[1], _alpha_bbox[3] + _p),
                        )
                        img_rgba = img_rgba.crop(_alpha_bbox)

                    img_rgba.thumbnail((400, 400), Image.LANCZOS)

                    _buf = _io.BytesIO()
                    img_rgba.save(_buf, format="PNG")
                    thumb = soften_edges(_buf.getvalue(), radius=0.5)
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

    Always uses flat-lay layout (tpl_flatlay.html):
      0 photos  -> flat-lay with all placeholder slots
      1+ photos -> flat-lay with real photos + placeholders for missing

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
        if real_photos == 0 and len(outfit_slots) > 0:
            logger.info("brief_card.all_placeholders",
                        total_slots=len(outfit_slots))

        # Common data
        date_str, context_str = prepare_date_context(user, child)
        weather_tpl = prepare_weather_data(weather)
        child_name = getattr(child, "name", "") if child else ""
        user_name = getattr(user, "name", "") if user else ""
        name = child_name or user_name or ""

        # Always flat-lay (0 photos = all placeholders, 1+ = real photos + placeholders)
        html = _build_flatlay_html(
            name, context_str, date_str, theme,
            weather_tpl, outfit_slots, outfit, advice_text,
            colortype,
        )

        png_bytes = await render_html_to_png(html)
        if png_bytes:
            logger.info("brief_card.rendered", size=len(png_bytes),
                        real_photos=real_photos)
            return png_bytes

        logger.warning("brief_card.render_failed")
        return None

    except Exception as e:
        logger.warning("brief_card.build_failed", error=str(e), exc_info=True)
        return None


# ── Flat-lay card (unified layout for all states) ────────────────────────────

def _build_flatlay_html(
    name: str, context_str: str, date_str: str, theme: dict,
    weather_tpl: dict, outfit_slots: list[dict], outfit: dict,
    advice_text: str, colortype: str = "",
    alert: dict | None = None,
) -> str:
    """Magazine-style flat-lay composition with absolute positioning.

    Used for ALL card states:
      - 0 photos: all placeholder slots
      - 1+ photos: real photos + placeholders for missing
      - morning update: with alert banner (pass alert dict)

    alert dict: {"type": "warn"|"ok", "icon": str, "header": str, "text": str}
    """
    from services.brief_renderer import prepare_items_flatlay
    items, placeholders, progress_pct, progress_text = prepare_items_flatlay(outfit_slots)
    palette = _collect_palette_rich(outfit_slots, colortype=colortype)

    return render_template(
        "tpl_flatlay.html",
        css_class=theme["css_class"],
        name=name,
        context=context_str,
        date_str=date_str,
        weather=weather_tpl,
        items=items,
        placeholders=placeholders,
        palette=palette,
        kassi_comment=advice_text,
        progress_pct=progress_pct,
        progress_text=progress_text,
        alert=alert,
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
    """Render morning update card using flat-lay layout + alert banner."""
    segment = get_segment(user)
    theme = get_theme(segment)
    date_str, context_str = prepare_date_context(user, child)

    child_name = getattr(child, "name", "") if child else ""
    user_name = getattr(user, "name", "") if user else ""
    name = child_name or user_name or ""

    weather_tpl = prepare_weather_data(weather_now)

    # Build alert banner
    if weather_changed:
        alert = {
            "type": "warn",
            "icon": "\u26a0\ufe0f",
            "header": change_text.split(".")[0] + "!" if change_text else "Погода изменилась!",
            "text": ". ".join(change_text.split(".")[1:]).strip() if "." in (change_text or "") else "",
        }
    else:
        alert = {
            "type": "ok",
            "icon": "\u2705",
            "header": "Всё как вчера планировали",
            "text": "",
        }

    # Download photos for slots
    await _download_slot_photos(evening_slots)

    html = _build_flatlay_html(
        name, context_str, date_str, theme,
        weather_tpl, evening_slots, {},
        kassi_comment, alert=alert,
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
