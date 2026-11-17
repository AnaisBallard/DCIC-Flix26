import os
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from bson import ObjectId
from bson.decimal128 import Decimal128
from fastapi import Depends, FastAPI, HTTPException, Query
from pymongo import MongoClient, DESCENDING
from pymongo.errors import PyMongoError

service_name = os.getenv("SERVICE_NAME", "catalog-service")
database_name = os.getenv("MONGODB_DATABASE", "peliculas-proyectos")
mongodb_uri = os.getenv(
    "MONGODB_URI",
    "mongodb://flix_catalog:catalog_local_dev@mongodb:27017/"
    "peliculas-proyectos?authSource=peliculas-proyectos",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.mongo_client = MongoClient(
        mongodb_uri, serverSelectionTimeoutMS=3000
    )
    try:
        yield
    finally:
        app.state.mongo_client.close()


app = FastAPI(title=f"DCIC-Flix26 {service_name}", lifespan=lifespan)


def get_database():
    return app.state.mongo_client[database_name]


def json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (Decimal128, Decimal)):
        return str(value.to_decimal() if isinstance(value, Decimal128) else value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def parse_movie_id(movie_id: str) -> ObjectId:
    if not ObjectId.is_valid(movie_id):
        raise HTTPException(status_code=422, detail="movie_id must be a MongoDB ObjectId")
    return ObjectId(movie_id)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        app.state.mongo_client.admin.command("ping")
    except PyMongoError as error:
        raise HTTPException(status_code=503, detail="MongoDB is unavailable") from error
    return {"status": "ok", "service": service_name}


@app.get("/movies")
def list_movies(
    q: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    genre: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    database=Depends(get_database),
) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    if q is not None:
        term = q.strip()
        if not term:
            raise HTTPException(status_code=422, detail="q must not be blank")
        pattern = re.escape(term)
        filters["$or"] = [
            {"title": {"$regex": pattern, "$options": "i"}},
            {"plot": {"$regex": pattern, "$options": "i"}},
            {"fullplot": {"$regex": pattern, "$options": "i"}},
        ]
    if genre is not None:
        normalized_genre = genre.strip()
        if not normalized_genre:
            raise HTTPException(status_code=422, detail="genre must not be blank")
        filters["genres"] = {
            "$regex": f"^{re.escape(normalized_genre)}$",
            "$options": "i",
        }

    collection = database["movies"]
    total = collection.count_documents(filters)
    cursor = (
        collection.find(filters)
        .sort([("title", 1), ("_id", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [json_safe(movie) for movie in cursor],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/movies/{movie_id}")
def get_movie(movie_id: str, database=Depends(get_database)) -> dict[str, Any]:
    object_id = parse_movie_id(movie_id)
    movie = database["movies"].find_one({"_id": object_id})
    if movie is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return json_safe(movie)


@app.get("/movies/{movie_id}/reviews")
def get_movie_reviews(
    movie_id: str,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    database=Depends(get_database),
) -> dict[str, Any]:
    object_id = parse_movie_id(movie_id)
    if database["movies"].find_one({"_id": object_id}, {"_id": 1}) is None:
        raise HTTPException(status_code=404, detail="Movie not found")

    filters = {"movie_id": object_id}
    collection = database["reviews"]
    total = collection.count_documents(filters)
    cursor = (
        collection.find(
            filters,
            {
                "_id": 1,
                "movie_id": 1,
                "user_id": 1,
                "rating": 1,
                "comment": 1,
                "date": 1,
            },
        )
        .sort([("date", DESCENDING), ("_id", DESCENDING)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [json_safe(review) for review in cursor],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
