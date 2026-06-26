from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # БД
    database_write_url: str
    database_read_url: str
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # Telegram
    telegram_bot_token: str
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    telegram_payment_token: str = ""

    # Anthropic (через запятую)
    anthropic_api_keys: str  # "key1,key2"

    @property
    def anthropic_keys_list(self) -> list[str]:
        return [k.strip() for k in self.anthropic_api_keys.split(",") if k.strip()]

    # Billing
    payment_provider: Literal["stars", "stripe", "paddle"] = "stars"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""

    # App
    environment: Literal["dev", "prod"] = "dev"
    sentry_dsn: str = ""
    admin_telegram_ids: str = ""

    # Cookbook (личная поваренная книга) — общий секрет доступа к AI-ассистенту/импорту
    cookbook_secret: str = ""
    cookbook_vision_daily_cap: int = 50

    @property
    def admin_ids_list(self) -> list[int]:
        return [int(i.strip()) for i in self.admin_telegram_ids.split(",") if i.strip()]

    # Storage (Фаза 2)
    cloudflare_r2_bucket: str = ""
    cloudflare_r2_access_key: str = ""
    cloudflare_r2_secret_key: str = ""
    cloudflare_r2_endpoint: str = ""
    cloudflare_r2_cdn_url: str = ""
    removebg_api_key: str = ""
    bg_removal_model: str = "silueta"  # "silueta" or "rmbg14"



settings = Settings()  # type: ignore[call-arg]
