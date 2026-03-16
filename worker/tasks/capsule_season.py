"""capsule_season task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("capsule_season.run")
    # TODO: implement
