"""unknown_items_report task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("unknown_items_report.run")
    # TODO: implement
