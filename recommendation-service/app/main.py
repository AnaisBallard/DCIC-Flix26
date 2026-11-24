import asyncio
import hashlib
import json
import logging
import os
import re
from contextlib import asynccontextmanager, suppress
from typing import Any

import aio_pika
from fastapi import FastAPI
from pymongo import MongoClient

logger = logging.getLogger("recommendation-service")
service_name = os.getenv("SERVICE_NAME", "recommendation-service")
READY_QUEUE = os.getenv(
    "RABBITMQ_CATALOG_READY_QUEUE", "recommendations.catalog-ready"
)
FINGERPRINT_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class RecommendationReadiness:
    def __init__(self) -> None:
        self.status = "waiting"
        self.source_fingerprint: str | None = None

    def catalog_ready_event(self, fingerprint: str) -> None:
        self.source_fingerprint = fingerprint
        self.status = "indexing"


def _read_catalog_state(database) -> dict[str, Any] | None:
    return database["_catalog_pipeline"].find_one({"_id": "catalog"})


def is_valid_catalog_ready_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    fingerprint = event.get("source_fingerprint")
    version = event.get("cleaner_version")
    event_id = event.get("event_id")
    if (
        event.get("event_type") != "catalog.cleaning.completed"
        or not isinstance(fingerprint, str)
        or not FINGERPRINT_PATTERN.fullmatch(fingerprint)
        or not isinstance(version, str)
        or not version
        or not isinstance(event_id, str)
    ):
        return False
    expected_id = hashlib.sha256(
        f"catalog.cleaning.completed|{fingerprint}|{version}".encode("utf-8")
    ).hexdigest()
    return event_id == expected_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoClient(
        os.environ["MONGODB_URI"],
        serverSelectionTimeoutMS=10000,
        tz_aware=True,
    )
    database = mongo[os.environ["MONGODB_DATABASE"]]
    readiness = RecommendationReadiness()
    state = await asyncio.to_thread(_read_catalog_state, database)
    if (
        state
        and state.get("cleaning_status") == "ready"
        and state.get("ready_event_status") == "sent"
    ):
        readiness.catalog_ready_event(state["source_fingerprint"])

    rabbit = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    channel = await rabbit.channel()
    queue = await channel.get_queue(READY_QUEUE, ensure=True)

    async def on_catalog_ready(message: aio_pika.IncomingMessage) -> None:
        try:
            event = json.loads(message.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Discarded malformed catalog-ready event")
            await message.reject(requeue=False)
            return
        if not is_valid_catalog_ready_event(event):
            logger.warning("Discarded invalid catalog-ready event")
            await message.reject(requeue=False)
            return

        fingerprint = event["source_fingerprint"]
        version = event["cleaner_version"]
        async with message.process(requeue=True):
            current_state = await asyncio.to_thread(
                _read_catalog_state, database
            )
            if (
                not current_state
                or current_state.get("cleaning_status") != "ready"
                or current_state.get("source_fingerprint") != fingerprint
                or current_state.get("cleaner_version") != version
            ):
                logger.info("Ignored stale catalog-ready event")
                return
            readiness.catalog_ready_event(fingerprint)
            logger.info("Catalog-ready event accepted; recommendation index is pending")

    consumer_tag = await queue.consume(on_catalog_ready, no_ack=False)
    app.state.readiness = readiness
    app.state.database = database
    app.state.rabbit = rabbit
    app.state.channel = channel
    app.state.consumer_tag = consumer_tag
    try:
        yield
    finally:
        await queue.cancel(consumer_tag)
        await channel.close()
        await rabbit.close()
        mongo.close()


app = FastAPI(title=f"DCIC-Flix26 {service_name}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": service_name}


@app.get("/status")
async def status() -> dict[str, Any]:
    readiness: RecommendationReadiness = app.state.readiness
    return {
        "status": readiness.status,
        "source_fingerprint": readiness.source_fingerprint,
        "recommendations_available": readiness.status == "ready",
    }
