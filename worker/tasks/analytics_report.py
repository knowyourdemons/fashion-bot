"""analytics_report task — stub."""
import structlog
logger = structlog.get_logger()

async def run() -> None:
    """Cron trigger."""
    logger.info("analytics_report.run")
    # TODO: implement
