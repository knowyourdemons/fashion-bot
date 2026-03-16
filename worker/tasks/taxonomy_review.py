"""taxonomy_review task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("taxonomy_review.run")
    # TODO: implement
