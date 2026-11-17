import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
import httpx
import pytest
from httpx import ASGITransport

service_main = Path(__file__).resolve().parents[1] / "app" / "main.py"
spec = importlib.util.spec_from_file_location("dcic_catalog_unit_app", service_main)
catalog_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog_module)
app = catalog_module.app
get_database = catalog_module.get_database

MOVIE_ID = ObjectId("573a13a4f29313caabd10527")


class Cursor:
    def __init__(self, items):
        self.items = items

    def sort(self, *_args):
        return self

    def skip(self, amount):
        self.items = self.items[amount:]
        return self

    def limit(self, amount):
        self.items = self.items[:amount]
        return self

    def __iter__(self):
        return iter(self.items)


class Collection:
    def __init__(self, documents):
        self.documents = documents
        self.last_filter = None
        self.last_projection = None

    def count_documents(self, filters):
        self.last_filter = filters
        return len(self.documents)

    def find(self, filters, projection=None):
        self.last_filter = filters
        self.last_projection = projection
        items = self.documents.copy()
        if projection:
            excluded = {key for key, include in projection.items() if not include}
            included = {key for key, include in projection.items() if include}
            if included:
                items = [
                    {key: value for key, value in item.items() if key in included}
                    for item in items
                ]
            else:
                items = [
                    {key: value for key, value in item.items() if key not in excluded}
                    for item in items
                ]
        return Cursor(items)

    def find_one(self, filters, projection=None):
        self.last_filter = filters
        if filters.get("_id") == MOVIE_ID:
            return self.documents[0] if self.documents else None
        return None


class Database:
    def __init__(self):
        self.movies = Collection(
            [
                {
                    "_id": MOVIE_ID,
                    "title": "A Fish Tale",
                    "genres": ["Animation"],
                    "year": 2000,
                }
            ]
        )
        self.reviews = Collection(
            [
                {
                    "_id": ObjectId("6af3753e68313c9a2da138a5"),
                    "movie_id": MOVIE_ID,
                    "user_id": "usr_0937",
                    "user_email": "private@example.test",
                    "rating": 4,
                    "comment": "A compelling watch.",
                    "date": datetime(2024, 3, 10, tzinfo=timezone.utc),
                }
            ]
        )

    def __getitem__(self, name):
        return getattr(self, name)


database = Database()
app.dependency_overrides[get_database] = lambda: database


@pytest.mark.asyncio
async def test_search_supports_pagination_and_genre_filter():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://catalog"
    ) as client:
        response = await client.get(
            "/movies", params={"q": "fish", "genre": "Animation", "page_size": 5}
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["_id"] == str(MOVIE_ID)
    assert response.json()["total"] == 1
    assert database.movies.last_filter["genres"]["$options"] == "i"
    assert database.movies.last_filter["$or"][0]["title"]["$regex"] == "fish"


@pytest.mark.asyncio
async def test_movie_details_returns_404_for_missing_object_id():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://catalog"
    ) as client:
        response = await client.get(f"/movies/{ObjectId()}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reviews_use_dataset_movie_id_and_do_not_expose_email():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://catalog"
    ) as client:
        response = await client.get(f"/movies/{MOVIE_ID}/reviews")

    assert response.status_code == 200
    review = response.json()["items"][0]
    assert review["movie_id"] == str(MOVIE_ID)
    assert review["rating"] == 4
    assert "user_email" not in review
    assert "user_email" not in database.reviews.last_projection
