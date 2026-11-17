import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from uuid import UUID

import aio_pika
from bson import ObjectId
from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

logger = logging.getLogger("dcic.consumer")
RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL", "amqp://flix:flix_local_dev_only@rabbitmq:5672/"
)
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://flix_consumer:consumer_local_dev@mongodb:27017/"
    "peliculas-proyectos?authSource=peliculas-proyectos",
)
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "peliculas-proyectos")
REVIEW_QUEUE = os.getenv("RABBITMQ_REVIEW_QUEUE", "interactions.reviews")


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: UUID
    movie_id: str = Field(pattern=r"^[a-fA-F0-9]{24}$")
    user_id: str = Field(min_length=1, max_length=128)
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(min_length=1, max_length=5000)


class ReviewEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["interaction.review.created"]
    occurred_at: datetime
    payload: ReviewPayload

    @model_validator(mode="after")
    def matching_event_ids(self) -> "ReviewEvent":
        if self.event_id != self.payload.event_id:
            raise ValueError("envelope and payload event_id must match")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return self


def persist_event(collection: Collection, event: ReviewEvent) -> bool:
    document = {
        "_id": str(event.event_id),
        "movie_id": ObjectId(event.payload.movie_id),
        "user_id": event.payload.user_id,
        "rating": event.payload.rating,
        "comment": event.payload.comment,
        "date": event.occurred_at,
        "event_type": event.event_type,
    }
    try:
        result = collection.update_one(
            {"_id": document["_id"]},
            {"$setOnInsert": document},
            upsert=True,
        )
    except DuplicateKeyError:
        logger.info("Duplicate event %s was already persisted.", event.event_id)
        return False
    return result.upserted_id is not None


async def process_message(message, collection: Collection) -> None:
    try:
        event = ReviewEvent.model_validate_json(message.body)
    except (ValidationError, ValueError, UnicodeDecodeError) as error:
        logger.warning("Rejecting invalid interaction event: %s", error)
        await message.reject(requeue=False)
        return

    try:
        await asyncio.to_thread(persist_event, collection, event)
    except PyMongoError:
        logger.exception("MongoDB persistence failed for event %s", event.event_id)
        await message.nack(requeue=True)
        return

    await message.ack()


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    connection = None
    queue = None
    consumer_tag = None
    try:
        await asyncio.to_thread(mongo_client.admin.command, "ping")
        connection = await aio_pika.connect_robust(RABBITMQ_URL, timeout=10)
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=10)
        queue = await channel.get_queue(REVIEW_QUEUE, ensure=True)
        collection = mongo_client[MONGODB_DATABASE]["reviews"]
        consumer_tag = await queue.consume(
            lambda message: process_message(message, collection), no_ack=False
        )
        app.state.mongo_client = mongo_client
        app.state.rabbitmq_connection = connection
        logger.info("Consuming durable queue %s.", REVIEW_QUEUE)
        yield
    finally:
        try:
            if queue is not None and consumer_tag is not None:
                await queue.cancel(consumer_tag)
        finally:
            try:
                if connection is not None and not connection.is_closed:
                    await connection.close()
            finally:
                mongo_client.close()


app = FastAPI(title="DCIC-Flix26 Consumer", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    try:
        request.app.state.mongo_client.admin.command("ping")
    except PyMongoError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB is unavailable",
        ) from error

    connection = request.app.state.rabbitmq_connection
    if connection.is_closed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RabbitMQ is unavailable",
        )
    return {"status": "ok", "service": "consumer"}
