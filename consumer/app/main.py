import asyncio
import logging


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logging.info("Consumer scaffold started; message handling is not implemented.")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
