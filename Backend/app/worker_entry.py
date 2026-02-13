import asyncio

from app.core.config import settings
from app.services.worker import worker_loop


async def main() -> None:
    await worker_loop(settings.worker_poll_interval_seconds)


if __name__ == '__main__':
    asyncio.run(main())
