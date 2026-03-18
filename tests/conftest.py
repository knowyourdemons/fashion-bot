import sys
import types
import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from datetime import date

# ── Заглушки для отсутствующих зависимостей (локальный запуск без Docker) ───
# Подключаем до любых импортов проекта — если модуль уже есть, не трогаем.
def _mock_if_missing(*names: str) -> None:
    for name in names:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

_mock_if_missing(
    "structlog",
    "redis", "redis.asyncio",
    "sentry_sdk", "sentry_sdk.integrations", "sentry_sdk.integrations.fastapi",
    "worker.fast_worker",
)

# Packages that cause issues when mocked but ARE installed in Docker:
# httpx      → metaclass conflict in starlette.testclient
# pydantic_settings → config.Settings(BaseSettings) inherits MagicMock, breaking DB URL
# Try real imports first; only mock if the package is truly absent.
def _try_real_import(*names: str) -> None:
    for name in names:
        if name not in sys.modules:
            try:
                import importlib
                importlib.import_module(name)
            except ImportError:
                sys.modules[name] = MagicMock()

_try_real_import("httpx", "pydantic_settings")

# pytz нужно мокировать отдельно: telegram.constants импортирует UTC из pytz,
# и если UTC будет MagicMock — datetime.datetime(tzinfo=UTC) упадёт с TypeError.
if "pytz" not in sys.modules:
    import datetime as _dt
    _pytz_mock = MagicMock()
    # telegram._utils.datetime использует pytz.utc (lowercase) и pytz.UTC (uppercase)
    _pytz_mock.utc = _dt.timezone.utc
    _pytz_mock.UTC = _dt.timezone.utc
    _pytz_mock.timezone = lambda tz: _dt.timezone.utc
    sys.modules["pytz"] = _pytz_mock

# config: try to import the real config module (works in Docker with env vars set).
# Fall back to a minimal MagicMock config only when real import fails (local dev without .env).
if "config" not in sys.modules:
    try:
        import config as _real_config  # noqa: F401 — side effect: adds to sys.modules
    except Exception:
        _cfg = types.ModuleType("config")
        _settings = MagicMock()
        _settings.environment = "dev"
        _settings.admin_telegram_ids = ""
        _settings.admin_ids_list = []
        _cfg.settings = _settings
        sys.modules["config"] = _cfg


# ── Фикстуры пользователя ──────────────────────────────────────────────────

@pytest.fixture
def fake_user():
    user = MagicMock()
    user.id = uuid.UUID("3b4da73e-0772-407c-915e-f6dd1610fcc3")
    user.telegram_id = 195169
    user.name = "Stas"
    user.city = "Vilnius"
    user.timezone = "Europe/Vilnius"
    user.plan = "premium"
    user.segment = "mom_girl"
    user.colortype = "Лето"
    user.onboarding_completed = True
    return user


@pytest.fixture
def fake_child():
    child = MagicMock()
    child.id = uuid.UUID("acf0100d-ca11-4fce-815e-c516af11e710")
    child.name = "Алиса"
    child.gender = "girl"
    child.colortype = "Лето"
    child.birthdate = date(2022, 9, 1)
    child.current_size = "98"
    return child


@pytest.fixture
def fake_wardrobe_item():
    item = MagicMock()
    item.id = uuid.uuid4()
    item.owner_id = uuid.UUID("acf0100d-ca11-4fce-815e-c516af11e710")
    item.owner_type = "child"
    item.category_group = "top"
    item.type = "свитшот"
    item.color = "розовый"
    item.season = ["spring", "autumn"]
    item.score_item = 7.5
    item.show_in_collage = True
    item.photo_id = "AgACtest123"
    item.photo_url = "wardrobe/test/item.png"
    item.last_worn = None
    item.deleted_at = None
    return item


@pytest.fixture
def fake_context(fake_user):
    context = MagicMock()
    context.user_data = {"db_user": fake_user}
    context.bot_data = {}
    context.bot = AsyncMock()
    return context


@pytest.fixture
def fake_update():
    update = MagicMock()
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    update.message.from_user = MagicMock()
    update.message.from_user.id = 195169
    return update


# ── Session-scoped event loop для integration тестов ──────────────────────
import asyncio as _asyncio

@pytest.fixture(scope="session")
def event_loop():
    """One event loop for all async tests — prevents DB pool loop mismatch."""
    policy = _asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()
