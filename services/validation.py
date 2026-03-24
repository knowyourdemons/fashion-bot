"""Shared validation for wardrobe items, outfits, and Vision output.

Central place for all validation rules — used by Vision, outfit engine,
morning brief, capsule, travel, and gap analysis.
"""
import structlog

logger = structlog.get_logger()

# ── Valid values ──────────────────────────────────────────────────────────

VALID_CATEGORY_GROUPS = frozenset({
    "top", "bottom", "one_piece", "outerwear", "footwear",
    "accessory", "bag", "base_layer", "underwear",
})

VALID_SEASONS = frozenset({"winter", "spring", "summer", "autumn"})

VALID_OCCASIONS = frozenset({
    "everyday", "sport", "formal", "home", "outdoor",
    "beach", "party", "office", "evening",
})

WARMTH_RANGE = (1, 5)
FORMALITY_RANGE = (1, 5)


# ── Item validation ──────────────────────────────────────────────────────

def validate_vision_item(data: dict) -> dict:
    """Validate and sanitize a single Vision-returned item before DB storage.

    Fixes invalid values in-place:
    - Unknown category_group → "top" (safe default)
    - Invalid season values → removed
    - Invalid occasion values → removed
    - formality/warmth out of range → clamped
    - Empty color → "неизвестный"
    """
    # Category group
    cg = (data.get("category_group") or "top").lower().strip()
    if cg not in VALID_CATEGORY_GROUPS:
        logger.warning("validation.invalid_category_group",
                       got=cg, item_type=data.get("type"))
        # Try to infer from type via normalize
        try:
            from services.normalize import normalize_type
            _, norm_cg = normalize_type(data.get("type", ""))
            if norm_cg and norm_cg in VALID_CATEGORY_GROUPS:
                cg = norm_cg
            else:
                cg = "top"
        except Exception:
            cg = "top"
    data["category_group"] = cg

    # Season array
    season = data.get("season")
    if season:
        if isinstance(season, str):
            season = [season]
        valid = [s for s in season if s in VALID_SEASONS]
        if len(valid) != len(season):
            logger.warning("validation.invalid_season",
                           got=season, valid=valid,
                           item_type=data.get("type"))
        if not valid:
            logger.warning("validation.all_seasons_invalid",
                           got=season, item_type=data.get("type"))
        data["season"] = valid if valid else None

    # Occasion array
    occasion = data.get("occasion")
    if occasion:
        if isinstance(occasion, str):
            occasion = [occasion]
        valid = [o for o in occasion if o in VALID_OCCASIONS]
        if len(valid) != len(occasion):
            logger.warning("validation.invalid_occasion",
                           got=occasion, valid=valid)
        data["occasion"] = valid if valid else None

    # Warmth level
    wl = data.get("warmth_level")
    if wl is not None:
        try:
            wl = int(wl)
            wl = max(WARMTH_RANGE[0], min(WARMTH_RANGE[1], wl))
            data["warmth_level"] = wl
        except (ValueError, TypeError):
            data["warmth_level"] = None

    # Formality level
    fl = data.get("formality_level")
    if fl is not None:
        try:
            fl = int(fl)
            fl = max(FORMALITY_RANGE[0], min(FORMALITY_RANGE[1], fl))
            data["formality_level"] = fl
        except (ValueError, TypeError):
            data["formality_level"] = None

    # Color
    color = (data.get("color") or "").strip()
    if not color:
        color = "неизвестный"
    data["color"] = color.lower()

    # Type
    item_type = (data.get("type") or "").strip()
    if not item_type:
        item_type = "вещь"
    data["type"] = item_type.lower()

    # Score breakdown values (Vision returns 1-3, validate range)
    breakdown = data.get("score_breakdown")
    if breakdown and isinstance(breakdown, dict):
        for k, v in breakdown.items():
            try:
                v_int = int(v)
                breakdown[k] = max(1, min(3, v_int))
            except (ValueError, TypeError):
                breakdown[k] = 2  # default mid-range
        data["score_breakdown"] = breakdown

    return data


# ── Wardrobe validation ──────────────────────────────────────────────────

def has_minimum_wardrobe(items: list) -> bool:
    """Check if wardrobe has enough items for an outfit (not just count but types)."""
    if len(items) < 2:
        return False
    has_top = any(getattr(i, "category_group", "") == "top" for i in items)
    has_bottom = any(getattr(i, "category_group", "") == "bottom" for i in items)
    has_one_piece = any(getattr(i, "category_group", "") == "one_piece" for i in items)
    return (has_top and has_bottom) or has_one_piece


def check_item_not_in_active_brief(item_id: str, user_id: str) -> bool:
    """Check if item is in today's or yesterday's BriefLog. Returns True if safe to delete."""
    # Implemented as async in the caller — this is just the sync signature doc
    pass
