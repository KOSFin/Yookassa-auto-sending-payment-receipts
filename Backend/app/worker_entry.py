import asyncio
import logging

from app.core.config import settings
from app.services.worker import worker_loop


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    )


async def main() -> None:
    configure_logging()
    logging.getLogger(__name__).info(
        'Starting worker process (poll_seconds=%s)',
        settings.worker_poll_interval_seconds,
    )
    await worker_loop(settings.worker_poll_interval_seconds)


if __name__ == '__main__':
    asyncio.run(main())
