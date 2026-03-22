"""i18n — dict-based internationalization for 2 languages."""
import random as _random

from services.i18n.ru import STRINGS as _RU
from services.i18n.en import STRINGS as _EN

_LANGS = {"ru": _RU, "en": _EN}


def t(key: str, lang: str = "ru", **kwargs) -> str:
    """Get localized string by key. Falls back to Russian."""
    strings = _LANGS.get(lang, _RU)
    text = strings.get(key) or _RU.get(key, key)
    if isinstance(text, list):
        text = _random.choice(text)
    return text.format(**kwargs) if kwargs else text


def get_user_lang(user) -> str:
    """Get language from user object."""
    return getattr(user, "language", None) or "ru"
