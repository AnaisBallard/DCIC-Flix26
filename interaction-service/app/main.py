import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

import aio_pika
from aio_pika import DeliveryMode, ExchangeType, Message
from aio_pika.exceptions import AMQPError
from fastapi import Depends, FastAPI, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

service_name = os.getenv("SERVICE_NAME", "interaction-service")
logger = logging.getLogger("dcic.interaction")
rabbitmq_url = os.getenv(
    "RABBITMQ_URL", "amqp://flix:flix_local_dev_only@rabbitmq:5672/"
)
exchange_name = os.getenv("RABBITMQ_EXCHANGE", "dcic.events")
routing_key = os.getenv(
    "RABBITMQ_REVIEW_ROUTING_KEY", "interaction.review.created"
)
MovieId = Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    movie_id: MovieId
    user_id: str = Field(min_length=1, max_length=128)
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(min_length=1, max_length=5000)


class ReviewPayload(ReviewInput):
    event_id: UUID


class ReviewEvent(BaseModel):
    event_id: UUID
    event_type: str = Field(pattern=r"^interaction\.review\.created$")
    occurred_at: datetime
    payload: ReviewPayload


class ReviewPublisher:
    def __init__(self) -> None:
        self.connection: aio_pika.RobustConnection | None = None
        self.channel: aio_pika.abc.AbstractRobustChannel | None = None
        self.exchange: aio_pika.abc.AbstractExchange | None = None

    async def connect(self) -> None:
        self.connection = await aio_pika.connect_robust(
            rabbitmq_url, timeout=10
        )
        self.channel = await self.connection.channel(
            publisher_confirms=True, on_return_raises=True
        )
        self.exchange = await self.channel.declare_exchange(
            exchange_name, ExchangeType.TOPIC, durable=True
        )

    async def close(self) -> None:
        if self.connection is not None and not self.connection.is_closed:
            await self.connection.close()

    def is_healthy(self) -> bool:
        return (
            self.connection is not None
            and not self.connection.is_closed
            and self.channel is not None
            and not self.channel.is_closed
        )

    async def publish(self, event: ReviewEvent) -> None:
        if not self.is_healthy() or self.exchange is None:
            raise RuntimeError("RabbitMQ publisher is not connected")
        message = Message(
            body=event.model_dump_json().encode("utf-8"),
            content_type="application/json",
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(event.event_id),
            timestamp=event.occurred_at,
            type=event.event_type,
        )
        await self.exchange.publish(
            message, routing_key=routing_key, mandatory=True
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    publisher = ReviewPublisher()
    await publisher.connect()
    app.state.publisher = publisher
    try:
        yield
    finally:
        await publisher.close()


app = FastAPI(title=f"DCIC-Flix26 {service_name}", lifespan=lifespan)


def get_publisher(request: Request) -> ReviewPublisher:
    return request.app.state.publisher


@app.get("/health")
async def health(
    publisher: Annotated[ReviewPublisher, Depends(get_publisher)],
) -> dict[str, str]:
    if not publisher.is_healthy():
        raise HTTPException(status_code=503, detail="RabbitMQ is unavailable")
    return {"status": "ok", "service": service_name}


@app.post("/interactions/reviews", status_code=status.HTTP_202_ACCEPTED)
async def create_review(
    review: ReviewInput,
    publisher: Annotated[ReviewPublisher, Depends(get_publisher)],
) -> dict[str, str]:
    event_id = uuid4()
    event = ReviewEvent(
        event_id=event_id,
        event_type="interaction.review.created",
        occurred_at=datetime.now(timezone.utc),
        payload=ReviewPayload(**review.model_dump(), event_id=event_id),
    )
    try:
        await publisher.publish(event)
    except (AMQPError, RuntimeError, OSError) as error:
        logger.exception("Could not publish interaction event %s", event_id)
        raise HTTPException(
            status_code=503, detail="Could not publish interaction to RabbitMQ"
        ) from error
    return {"status": "accepted", "event_id": str(event_id)}
