import importlib.util
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from uuid import uuid4

import pytest
from bson import ObjectId

service_main = Path(__file__).resolve().parents[1] / "app" / "main.py"
spec = importlib.util.spec_from_file_location("dcic_consumer_unit_app", service_main)
consumer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(consumer_module)
ReviewEvent = consumer_module.ReviewEvent
persist_event = consumer_module.persist_event
process_message = consumer_module.process_message

MOVIE_ID = "573a13a4f29313caabd10527"


def make_event(event_id=None, **payload_updates):
    event_id = event_id or uuid4()
    payload = {
        "event_id": str(event_id),
        "movie_id": MOVIE_ID,
        "user_id": "usr_test",
        "rating": 4,
        "comment": "A compelling watch.",
        **payload_updates,
    }
    return {
        "event_id": str(event_id),
        "event_type": "interaction.review.created",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }


class FakeResult:
    def __init__(self, upserted_id):
        self.upserted_id = upserted_id


class FakeCollection:
    def __init__(self):
        self.calls = []
        self.documents = {}

    def update_one(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        event_id = args[0]["_id"]
        if event_id in self.documents:
            return FakeResult(None)
        self.documents[event_id] = args[1]["$setOnInsert"]
        return FakeResult(event_id)


class FakeMessage:
    def __init__(self, body):
        self.body = body
        self.acked = False
        self.rejected = None
        self.nacked = None

    async def ack(self):
        self.acked = True

    async def reject(self, requeue):
        self.rejected = requeue

    async def nack(self, requeue):
        self.nacked = requeue


@pytest.mark.asyncio
async def test_valid_event_is_persisted_before_ack():
    collection = FakeCollection()
    message = FakeMessage(json.dumps(make_event()).encode())

    await process_message(message, collection)

    assert message.acked
    assert message.rejected is None
    query, update = collection.calls[0][0]
    assert query["_id"]
    assert update["$setOnInsert"]["movie_id"] == ObjectId(MOVIE_ID)
    assert "user_email" not in update["$setOnInsert"]
    assert len(collection.documents) == 1


@pytest.mark.asyncio
async def test_invalid_event_is_rejected_without_requeue():
    collection = FakeCollection()
    event = make_event(rating=6)
    message = FakeMessage(json.dumps(event).encode())

    await process_message(message, collection)

    assert message.rejected is False
    assert not message.acked
    assert collection.calls == []


@pytest.mark.asyncio
async def test_mongo_failure_nacks_for_retry(monkeypatch):
    from pymongo.errors import AutoReconnect

    def fail(_collection, _event):
        raise AutoReconnect("temporary outage")

    monkeypatch.setattr(consumer_module, "persist_event", fail)
    message = FakeMessage(json.dumps(make_event()).encode())

    await process_message(message, FakeCollection())

    assert message.nacked is True
    assert not message.acked


def test_persistence_is_idempotent_by_event_id():
    event = ReviewEvent.model_validate(make_event())
    collection = FakeCollection()

    created = persist_event(collection, event)
    created_again = persist_event(collection, event)

    assert created
    assert not created_again
    assert len(collection.calls) == 2
    assert len(collection.documents) == 1


def test_health_requires_mongo_and_rabbitmq():
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                mongo_client=SimpleNamespace(
                    admin=SimpleNamespace(command=lambda _command: {"ok": 1})
                ),
                rabbitmq_connection=SimpleNamespace(is_closed=False),
            )
        )
    )

    assert consumer_module.health(request) == {
        "status": "ok",
        "service": "consumer",
    }


def test_health_reports_closed_rabbitmq():
    from fastapi import HTTPException

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                mongo_client=SimpleNamespace(
                    admin=SimpleNamespace(command=lambda _command: {"ok": 1})
                ),
                rabbitmq_connection=SimpleNamespace(is_closed=True),
            )
        )
    )

    with pytest.raises(HTTPException) as error:
        consumer_module.health(request)

    assert error.value.status_code == 503
