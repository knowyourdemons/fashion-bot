"""growth_alert task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("growth_alert.run")
    # TODO: implement
