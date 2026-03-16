"""subscription_expiry task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("subscription_expiry.run")
    # TODO: implement
