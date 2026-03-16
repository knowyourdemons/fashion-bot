"""declutter task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("declutter.run")
    # TODO: implement
