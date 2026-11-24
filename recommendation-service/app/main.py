import asyncio
import hashlib
import json
import logging
import math
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

import aio_pika
from bson import ObjectId
from bson.decimal128 import Decimal128
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import PyMongoError

from .recommender import (
    INDEX_VERSION,
    build_neighbor_documents,
    make_index_id,
    persist_neighbor_documents,
    rank_personalized_neighbors,
)

logger = logging.getLogger("dcic.recommendation")
DATABASE_NAME = os.getenv("MONGODB_DATABASE", "peliculas-proyectos")
MONGODB_URI = os.getenv(
    "MONGODB_URI",
    "mongodb://flix_recommendation:recommendation_local_dev@mongodb:27017/"
    "peliculas-proyectos?authSource=peliculas-proyectos",
)
RABBITMQ_URL = os.getenv(
    "RABBITMQ_URL", "amqp://flix:flix_local_dev_only@rabbitmq:5672/"
)
READY_QUEUE = os.getenv(
    "RABBITMQ_CATALOG_READY_QUEUE", "recommendations.catalog-ready"
)
EVENT_TYPE = "catalog.cleaning.completed"
POLL_INTERVAL = 5
LEASE_DURATION = timedelta(minutes=30)
MAX_RETRY_DELAY = 30 * 60
MOVIE_ID_PATTERN = r"^[a-fA-F0-9]{24}$"
MovieId = Annotated[str, Path(pattern=MOVIE_ID_PATTERN)]


def json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (Decimal128, Decimal)):
        return str(value.to_decimal() if isinstance(value, Decimal128) else value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def is_valid_catalog_ready_event(event: Any) -> bool:
    if not isinstance(event, dict):
        return False
    fingerprint = event.get("source_fingerprint")
    cleaner_version = event.get("cleaner_version")
    if (
        event.get("event_type") != EVENT_TYPE
        or not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or not isinstance(cleaner_version, str)
        or not cleaner_version
    ):
        return False
    expected_id = hashlib.sha256(
        f"{EVENT_TYPE}|{fingerprint}|{cleaner_version}".encode("utf-8")
    ).hexdigest()
    return event.get("event_id") == expected_id


def recommendation_status(
    catalog_state: dict[str, Any] | None,
    index_state: dict[str, Any] | None,
) -> dict[str, Any]:
    fingerprint = (
        catalog_state.get("source_fingerprint") if catalog_state else None
    )
    cleaner_version = catalog_state.get("cleaner_version") if catalog_state else None
    catalog_ready = bool(
        catalog_state
        and catalog_state.get("cleaning_status") == "ready"
        and catalog_state.get("ready_event_status") == "sent"
        and isinstance(fingerprint, str)
        and isinstance(cleaner_version, str)
    )

    status = "waiting"
    error_code = None
    if catalog_ready:
        expected_index_id = make_index_id(fingerprint, cleaner_version)
        current_index = bool(
            index_state
            and index_state.get("active_index_id") == expected_index_id
            and index_state.get("source_fingerprint") == fingerprint
            and index_state.get("cleaner_version") == cleaner_version
            and index_state.get("index_version") == INDEX_VERSION
        )
        if current_index and index_state.get("index_status") == "ready":
            status = "ready"
        elif current_index and index_state.get("index_status") == "failed":
            status = "failed"
            error_code = index_state.get("error_code")
        else:
            status = "indexing"

    return {
        "status": status,
        "source_fingerprint": fingerprint if catalog_ready else None,
        "recommendations_available": status == "ready",
        "error_code": error_code,
        "updated_at": (
            json_safe(index_state.get("updated_at"))
            if status in {"ready", "failed"} and index_state
            else None
        ),
    }


def get_database(request: Request):
    return request.app.state.database


def _catalog_state(database) -> dict[str, Any] | None:
    return database["_catalog_pipeline"].find_one({"_id": "catalog"})


def _index_state(database) -> dict[str, Any] | None:
    return database["_recommendation_index_state"].find_one({"_id": "active"})


def _ready_index(database) -> tuple[dict[str, Any], str]:
    catalog = _catalog_state(database)
    index_state = _index_state(database)
    state = recommendation_status(catalog, index_state)
    if state["status"] != "ready":
        raise HTTPException(
            status_code=503,
            detail=f"Recommendations are unavailable ({state['status']})",
        )
    return index_state, index_state["active_index_id"]


def run_index_cycle(database) -> None:
    catalog_state = _catalog_state(database)
    if not catalog_state or not (
        catalog_state.get("cleaning_status") == "ready"
        and catalog_state.get("ready_event_status") == "sent"
    ):
        return

    fingerprint = catalog_state.get("source_fingerprint")
    cleaner_version = catalog_state.get("cleaner_version")
    if not isinstance(fingerprint, str) or not isinstance(cleaner_version, str):
        return

    index_id = make_index_id(fingerprint, cleaner_version)
    state_collection = database["_recommendation_index_state"]
    current_state = state_collection.find_one({"_id": "active"})
    if recommendation_status(catalog_state, current_state)["status"] == "ready":
        return

    now = datetime.now(timezone.utc)
    retry_ready = {
        "index_status": "failed",
        "$or": [
            {"next_retry_at": {"$lte": now}},
            {"next_retry_at": {"$exists": False}},
        ],
    }
    claimable_states = [
        {"active_index_id": {"$ne": index_id}},
        {"index_status": {"$in": ["waiting", "pending"]}},
        retry_ready,
        {
            "index_status": "indexing",
            "$or": [
                {"lease_until": {"$lte": now}},
                {"lease_until": {"$exists": False}},
            ],
        },
    ]
    lease_owner = hashlib.sha256(
        f"{index_id}|{now.isoformat()}|{os.getpid()}".encode("utf-8")
    ).hexdigest()
    claimed_state = state_collection.find_one_and_update(
        {
            "_id": "active",
            "updated_at": current_state.get("updated_at") if current_state else None,
            "$or": claimable_states,
        },
        {
            "$set": {
                "index_status": "indexing",
                "active_index_id": index_id,
                "source_fingerprint": fingerprint,
                "cleaner_version": cleaner_version,
                "index_version": INDEX_VERSION,
                "lease_owner": lease_owner,
                "lease_until": now + LEASE_DURATION,
                "started_at": now,
                "updated_at": now,
                "error_code": None,
            },
            "$unset": {"next_retry_at": ""},
            "$inc": {"attempt": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    if claimed_state is None:
        return

    try:
        movies = list(
            database["movies"].find(
                {},
                {
                    "_id": 1,
                    "title": 1,
                    "genres": 1,
                    "directors": 1,
                    "cast": 1,
                    "plot": 1,
                    "fullplot": 1,
                },
            )
        )
        neighbor_documents = build_neighbor_documents(movies)
        persist_neighbor_documents(
            database["_recommendation_neighbors"], index_id, neighbor_documents
        )

        latest_catalog = _catalog_state(database)
        if (
            not latest_catalog
            or latest_catalog.get("cleaning_status") != "ready"
            or latest_catalog.get("ready_event_status") != "sent"
            or latest_catalog.get("source_fingerprint") != fingerprint
            or latest_catalog.get("cleaner_version") != cleaner_version
        ):
            state_collection.update_one(
                {"_id": "active", "lease_owner": lease_owner},
                {
                    "$set": {
                        "index_status": "waiting",
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$unset": {"lease_owner": "", "lease_until": ""},
                },
            )
            return

        result = state_collection.update_one(
            {
                "_id": "active",
                "index_status": "indexing",
                "lease_owner": lease_owner,
                "active_index_id": index_id,
            },
            {
                "$set": {
                    "index_status": "ready",
                    "movie_count": len(movies),
                    "completed_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc),
                },
                "$unset": {
                    "lease_owner": "",
                    "lease_until": "",
                    "next_retry_at": "",
                    "error_code": "",
                },
            },
        )
        if result.modified_count != 1:
            raise RuntimeError("Recommendation index lease was lost")
    except Exception as error:
        attempt = int(claimed_state.get("attempt", 1))
        retry_delay = min(30 * (2 ** min(attempt - 1, 10)), MAX_RETRY_DELAY)
        failed_at = datetime.now(timezone.utc)
        state_collection.update_one(
            {"_id": "active", "lease_owner": lease_owner},
            {
                "$set": {
                    "index_status": "failed",
                    "error_code": "index_build_failed",
                    "next_retry_at": failed_at + timedelta(seconds=retry_delay),
                    "updated_at": failed_at,
                },
                "$unset": {"lease_owner": "", "lease_until": ""},
            },
        )
        logger.error(
            "Recommendation index build failed (%s)", type(error).__name__
        )
        return

    database["_recommendation_neighbors"].delete_many(
        {"index_id": {"$ne": index_id}}
    )


async def _consume_catalog_ready(message: aio_pika.IncomingMessage, database) -> None:
    try:
        event = json.loads(message.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("Discarded invalid catalog-ready event")
        await message.reject(requeue=False)
        return
    if not is_valid_catalog_ready_event(event):
        logger.warning("Discarded invalid catalog-ready event")
        await message.reject(requeue=False)
        return

    async with message.process(requeue=True):
        await asyncio.to_thread(run_index_cycle, database)


async def _index_worker(database, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(run_index_cycle, database)
        except asyncio.CancelledError:
            raise
        except PyMongoError as error:
            logger.error("Recommendation worker database error (%s)", type(error).__name__)
        except Exception as error:
            logger.error("Recommendation worker cycle failed (%s)", type(error).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_INTERVAL)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo = MongoClient(
        MONGODB_URI, serverSelectionTimeoutMS=10000, tz_aware=True
    )
    rabbit = None
    worker = None
    try:
        mongo.admin.command("ping")
        database = mongo[DATABASE_NAME]
        database["_recommendation_index_state"].update_one(
            {"_id": "active"},
            {
                "$setOnInsert": {
                    "index_status": "waiting",
                    "attempt": 0,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        rabbit = await aio_pika.connect_robust(RABBITMQ_URL, timeout=10)
        channel = await rabbit.channel()
        await channel.set_qos(prefetch_count=1)
        exchange = await channel.declare_exchange(
            "dcic.events", aio_pika.ExchangeType.TOPIC, durable=True
        )
        queue = await channel.declare_queue(READY_QUEUE, durable=True)
        await queue.bind(exchange, routing_key=EVENT_TYPE)
        await queue.consume(
            lambda message: _consume_catalog_ready(message, database)
        )
        app.state.database = database
        app.state.mongo_client = mongo
        app.state.rabbit_connection = rabbit
        worker_stop = asyncio.Event()
        worker = asyncio.create_task(_index_worker(database, worker_stop))
        app.state.worker_stop = worker_stop
        app.state.worker = worker
        yield
    finally:
        if worker is not None:
            app.state.worker_stop.set()
            await worker
        if rabbit is not None and not rabbit.is_closed:
            await rabbit.close()
        mongo.close()


app = FastAPI(title="DCIC-Flix26 Recommendation Service", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    try:
        request.app.state.mongo_client.admin.command("ping")
    except PyMongoError as error:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable") from error
    if request.app.state.rabbit_connection.is_closed:
        raise HTTPException(status_code=503, detail="RabbitMQ is unavailable")
    return {"status": "ok", "service": "recommendation-service"}


@app.get("/status")
def status(database=Depends(get_database)) -> dict[str, Any]:
    return recommendation_status(_catalog_state(database), _index_state(database))


def _movie_results(database, ranked: list[tuple[Any, float]]) -> list[dict[str, Any]]:
    if not ranked:
        return []
    movie_ids = [movie_id for movie_id, _ in ranked]
    movies = {
        movie["_id"]: movie
        for movie in database["movies"].find({"_id": {"$in": movie_ids}})
    }
    items = []
    for movie_id, score in ranked:
        movie = movies.get(movie_id)
        if movie is not None:
            item = json_safe(movie)
            item["recommendation_score"] = float(score)
            items.append(item)
    return items


@app.get("/recommendations/{user_id}")
def personalized_recommendations(
    user_id: Annotated[str, Path(min_length=1, max_length=128)],
    database=Depends(get_database),
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
) -> dict[str, Any]:
    _, index_id = _ready_index(database)
    ratings: dict[ObjectId, int] = {}
    seen_movie_ids: set[ObjectId] = set()
    for review in database["reviews"].find(
        {"user_id": user_id},
        {"movie_id": 1, "rating": 1, "date": 1},
    ).sort([("date", -1), ("_id", -1)]):
        movie_id = review.get("movie_id")
        rating = review.get("rating")
        if (
            isinstance(movie_id, ObjectId)
            and movie_id not in seen_movie_ids
            and isinstance(rating, int)
            and not isinstance(rating, bool)
            and 1 <= rating <= 5
        ):
            seen_movie_ids.add(movie_id)
            ratings[movie_id] = rating

    if not ratings:
        return {"items": [], "total": 0, "reason": "no_rating_history"}

    neighbor_documents = database["_recommendation_neighbors"].find(
        {
            "index_id": index_id,
            "source_movie_id": {"$in": list(ratings)},
        },
        {"source_movie_id": 1, "neighbors": 1},
    )
    neighbors_by_movie = {
        document["source_movie_id"]: document.get("neighbors", [])
        for document in neighbor_documents
    }
    ranked = rank_personalized_neighbors(
        ratings, neighbors_by_movie, limit=limit
    )
    items = _movie_results(database, ranked)
    return {
        "items": items,
        "total": len(items),
        "reason": "ok" if items else "no_unwatched_neighbors",
    }


@app.get("/movies/{movie_id}/similar")
def similar_movies(
    movie_id: MovieId,
    database=Depends(get_database),
    limit: Annotated[int, Query(ge=1, le=30)] = 12,
) -> dict[str, Any]:
    _, index_id = _ready_index(database)
    object_id = ObjectId(movie_id)
    movie = database["movies"].find_one({"_id": object_id}, {"_id": 1})
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    neighbor_document = database["_recommendation_neighbors"].find_one(
        {"index_id": index_id, "source_movie_id": object_id},
        {"neighbors": 1},
    )
    neighbors = neighbor_document.get("neighbors", []) if neighbor_document else []
    ranked = [
        (neighbor["movie_id"], float(neighbor["score"]))
        for neighbor in neighbors[:limit]
        if isinstance(neighbor.get("score"), (int, float))
        and math.isfinite(neighbor["score"])
    ]
    items = _movie_results(database, ranked)
    return {
        "items": items,
        "total": len(items),
        "reason": "ok" if items else "no_similar_movies",
        "source_movie_id": movie_id,
    }
