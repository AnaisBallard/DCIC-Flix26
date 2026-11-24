import asyncio
import hashlib
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import aio_pika
from fastapi import FastAPI, HTTPException, Path, Query, Request
from pymongo import MongoClient, ReturnDocument

from .llm import LLMConfigurationError, LLMResponseError
from .pipeline import AUDIT_DETAILS, AUDIT_RUNS, CleaningError, json_safe, run_cleaning

logger = logging.getLogger("cleaning-agent")
service_name = os.getenv("SERVICE_NAME", "cleaning-agent")
CLEANER_VERSION = os.getenv("CLEANER_VERSION", "1")
LEASE_DURATION = timedelta(minutes=15)
POLL_INTERVAL = 5
EVENT_ROUTING_KEY = "catalog.cleaning.completed"
RUN_ID_PATTERN = "^[a-f0-9]{64}$"


def _error_code(error: Exception) -> str:
    if isinstance(error, LLMConfigurationError):
        return "llm_not_configured"
    if isinstance(error, LLMResponseError):
        return "llm_provider_error"
    return "cleaning_failed"


def _claim_run(database, owner: str) -> dict[str, Any] | None:
    state_collection = database["_catalog_pipeline"]
    state = state_collection.find_one({"_id": "catalog"})
    if not state or not state.get("source_fingerprint"):
        return None

    now = datetime.now(timezone.utc)
    if state.get("cleaner_version") != CLEANER_VERSION:
        return None
    if (
        state.get("cleaning_status") == "ready"
        and state.get("run_id")
        and state.get("ready_event_status") in ("pending", "sent")
    ):
        return None
    if state.get("cleaning_status") == "failed":
        retry_at = state.get("next_retry_at")
        if retry_at and retry_at > now:
            return None

    claimable = {
        "$or": [
            {"cleaning_status": {"$in": ["pending", "failed"]}},
            {"cleaning_status": "running", "lease_until": {"$lte": now}},
            {"cleaning_status": "running", "lease_until": {"$exists": False}},
        ]
    }
    return state_collection.find_one_and_update(
        {
            "_id": "catalog",
            "source_fingerprint": state["source_fingerprint"],
            "cleaner_version": CLEANER_VERSION,
            **claimable,
        },
        {
            "$set": {
                "cleaning_status": "running",
                "lease_owner": owner,
                "lease_until": now + LEASE_DURATION,
                "started_at": now,
                "updated_at": now,
                "error_code": None,
            },
            "$inc": {"attempt": 1},
            "$unset": {"next_retry_at": ""},
        },
        return_document=ReturnDocument.AFTER,
    )


def _heartbeat(database, owner: str) -> None:
    now = datetime.now(timezone.utc)
    result = database["_catalog_pipeline"].update_one(
        {
            "_id": "catalog",
            "cleaning_status": "running",
            "lease_owner": owner,
        },
        {
            "$set": {
                "lease_until": now + LEASE_DURATION,
                "updated_at": now,
            }
        },
    )
    if result.modified_count != 1:
        raise CleaningError("Cleaning lease was lost")


def run_cleaning_cycle(database) -> None:
    owner = uuid.uuid4().hex
    claimed = _claim_run(database, owner)
    if claimed is None:
        return

    fingerprint = claimed["source_fingerprint"]
    version = claimed["cleaner_version"]
    run_id = hashlib.sha256(f"{fingerprint}|{version}".encode("utf-8")).hexdigest()

    def heartbeat() -> None:
        _heartbeat(database, owner)

    try:
        summary = run_cleaning(
            database,
            source_fingerprint=fingerprint,
            cleaner_version=version,
            heartbeat=heartbeat,
        )
    except Exception as error:
        code = _error_code(error)
        now = datetime.now(timezone.utc)
        attempts = claimed.get("attempt", 1)
        retry_seconds = min(60 * (2 ** min(max(attempts - 1, 0), 4)), 900)
        result = database["_catalog_pipeline"].update_one(
            {
                "_id": "catalog",
                "cleaning_status": "running",
                "lease_owner": owner,
            },
            {
                "$set": {
                    "cleaning_status": "failed",
                    "error_code": code,
                    "updated_at": now,
                    "next_retry_at": now + timedelta(seconds=retry_seconds),
                },
                "$unset": {"lease_owner": "", "lease_until": ""},
            },
        )
        if result.modified_count != 1:
            raise CleaningError("Cleaning lease was lost while recording failure")
        database[AUDIT_RUNS].update_one(
            {"_id": run_id},
            {
                "$set": {
                    "run_id": run_id,
                    "source_fingerprint": fingerprint,
                    "cleaner_version": version,
                    "status": "failed",
                    "error_code": code,
                    "updated_at": now,
                },
                "$setOnInsert": {"started_at": claimed["started_at"]},
            },
            upsert=True,
        )
        logger.error("Catalog cleaning failed with code %s", code)
        return

    now = datetime.now(timezone.utc)
    result = database["_catalog_pipeline"].update_one(
        {
            "_id": "catalog",
            "cleaning_status": "running",
            "lease_owner": owner,
        },
        {
            "$set": {
                "cleaning_status": "ready",
                "ready_event_status": "pending",
                "run_id": summary["run_id"],
                "metrics": summary["metrics"],
                "completed_at": now,
                "updated_at": now,
                "error_code": None,
            },
            "$unset": {
                "lease_owner": "",
                "lease_until": "",
                "next_retry_at": "",
            },
        },
    )
    if result.modified_count != 1:
        raise CleaningError("Cleaning lease was lost before completion")


async def _publish_ready_event(database, exchange) -> None:
    state = database["_catalog_pipeline"].find_one(
        {"_id": "catalog", "cleaning_status": "ready", "ready_event_status": "pending"}
    )
    if not state:
        return

    fingerprint = state["source_fingerprint"]
    version = state["cleaner_version"]
    event_id = hashlib.sha256(
        f"{EVENT_ROUTING_KEY}|{fingerprint}|{version}".encode("utf-8")
    ).hexdigest()
    event = {
        "event_id": event_id,
        "event_type": EVENT_ROUTING_KEY,
        "source_fingerprint": fingerprint,
        "cleaner_version": version,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    message = aio_pika.Message(
        body=json.dumps(event).encode("utf-8"),
        message_id=event_id,
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await exchange.publish(message, routing_key=EVENT_ROUTING_KEY, mandatory=True)
    database["_catalog_pipeline"].update_one(
        {
            "_id": "catalog",
            "source_fingerprint": fingerprint,
            "cleaner_version": version,
            "ready_event_status": "pending",
        },
        {
            "$set": {
                "ready_event_status": "sent",
                "ready_event_id": event_id,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )


async def _worker(database, exchange, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_cleaning_cycle, database)
            await _publish_ready_event(database, exchange)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Cleaning worker cycle failed (%s)", type(error).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoClient(
        os.environ["MONGODB_URI"],
        serverSelectionTimeoutMS=10000,
        tz_aware=True,
    )
    database = mongo[os.environ["MONGODB_DATABASE"]]
    rabbit = await aio_pika.connect_robust(os.environ["RABBITMQ_URL"])
    channel = await rabbit.channel(publisher_confirms=True)
    exchange = await channel.declare_exchange(
        "dcic.events", aio_pika.ExchangeType.TOPIC, durable=True
    )
    stop = asyncio.Event()
    worker = asyncio.create_task(_worker(database, exchange, stop))
    app.state.database = database
    try:
        yield
    finally:
        stop.set()
        await worker
        await channel.close()
        await rabbit.close()
        mongo.close()


app = FastAPI(title=f"DCIC-Flix26 {service_name}", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": service_name}


@app.get("/status")
async def status(request: Request) -> dict[str, Any]:
    state = request.app.state.database["_catalog_pipeline"].find_one(
        {"_id": "catalog"}
    )
    if not state:
        return {
            "cleaning_status": "pending",
            "source_fingerprint": None,
            "cleaner_version": CLEANER_VERSION,
            "updated_at": None,
            "error_code": None,
        }
    current_version = state.get("cleaner_version") == CLEANER_VERSION
    return {
        "cleaning_status": (
            state.get("cleaning_status", "pending")
            if current_version
            else "pending"
        ),
        "source_fingerprint": state.get("source_fingerprint"),
        "cleaner_version": state.get("cleaner_version"),
        "updated_at": json_safe(state.get("updated_at")),
        "error_code": state.get("error_code") if current_version else None,
    }


@app.get("/audit/runs")
async def audit_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    collection = request.app.state.database[AUDIT_RUNS]
    items = list(
        collection.find({}, {"_id": 0}).sort("started_at", -1).skip(offset).limit(limit)
    )
    return {
        "items": json_safe(items),
        "total": collection.count_documents({}),
        "limit": limit,
        "offset": offset,
    }


@app.get("/audit/runs/{run_id}/details")
async def audit_run_details(
    request: Request,
    run_id: Annotated[str, Path(pattern=RUN_ID_PATTERN)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    database = request.app.state.database
    if not database[AUDIT_RUNS].find_one({"_id": run_id}):
        raise HTTPException(status_code=404, detail="Audit run not found")
    collection = database[AUDIT_DETAILS]
    items = list(
        collection.find({"run_id": run_id}, {"_id": 0})
        .sort("updated_at", 1)
        .skip(offset)
        .limit(limit)
    )
    return {
        "items": json_safe(items),
        "total": collection.count_documents({"run_id": run_id}),
        "limit": limit,
        "offset": offset,
    }
