"""i18n — dict-based internationalization for 2 languages."""
import random as _random

from services.i18n.ru import STRINGS as _RU
from services.i18n.en import STRINGS as _EN

_LANGS = {"ru": _RU, "en": _EN}

# Common constants injected into every t() call as defaults.
# Templates can use {trial_days}, {photo_target}, etc. without explicit kwargs.
def _common_vars() -> dict[str, str]:
    from core.permissions import (
        TRIAL_DAYS, PHOTO_TARGET, MIN_ITEMS_GAP_ANALYSIS,
        premium_features_text,
    )
    pf = premium_features_text()
    return {
        "trial_days": str(TRIAL_DAYS),
        "photo_target": str(PHOTO_TARGET),
        "min_items": str(MIN_ITEMS_GAP_ANALYSIS),
        "premium_wardrobe": pf["wardrobe"],
        "premium_photos": pf["photos"],
        "premium_chat": pf["chat"],
        "premium_children": pf["children"],
    }

_COMMON: dict[str, str] | None = None


def t(key: str, lang: str = "ru", **kwargs) -> str:
    """Get localized string by key. Falls back to Russian."""
    global _COMMON
    if _COMMON is None:
        try:
            _COMMON = _common_vars()
        except Exception:
            _COMMON = {}
    strings = _LANGS.get(lang, _RU)
    text = strings.get(key) or _RU.get(key, key)
    if isinstance(text, list):
        text = _random.choice(text)
    if not kwargs and not _COMMON:
        return text
    merged = {**_COMMON, **kwargs}  # explicit kwargs override defaults
    return text.format(**merged) if merged else text


def get_user_lang(user) -> str:
    """Get language from user object."""
    return getattr(user, "language", None) or "ru"
