"""Backend application entry point."""

import asyncio

from application import Application
from models import ApplicationConfig


async def main() -> None:
    """Build and run the backend application."""
    application = Application(
        config=ApplicationConfig(),
    )

    await application.run()


try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\nApplication stopped.")