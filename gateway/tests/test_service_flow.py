import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from bson import ObjectId
from httpx import ASGITransport

ROOT = Path(__file__).resolve().parents[2]
MOVIE_ID = ObjectId("573a13a4f29313caabd10527")


def load_service(name, relative_path):
    module_name = f"dcic_{name}_integration_app"
    spec = importlib.util.spec_from_file_location(
        module_name, ROOT / relative_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


gateway_module = load_service("gateway", "gateway/app/main.py")
gateway_app = gateway_module.app
get_http_client = gateway_module.get_http_client
catalog_module = load_service("catalog", "catalog-service/app/main.py")
interaction_module = load_service(
    "interaction", "interaction-service/app/main.py"
)


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

    def count_documents(self, _filters):
        return len(self.documents)

    def find(self, _filters, projection=None):
        items = self.documents.copy()
        if projection:
            excluded = {key for key, include in projection.items() if not include}
            items = [
                {key: value for key, value in item.items() if key not in excluded}
                for item in items
            ]
        return Cursor(items)

    def find_one(self, filters, _projection=None):
        if filters.get("_id") == MOVIE_ID:
            return self.documents[0]
        return None


class Database:
    def __init__(self):
        self.collections = {
            "movies": Collection(
                [
                    {
                        "_id": MOVIE_ID,
                        "title": "A Fish Tale",
                        "genres": ["Animation"],
                    }
                ]
            ),
            "reviews": Collection(
                [
                    {
                        "_id": ObjectId(),
                        "movie_id": MOVIE_ID,
                        "user_id": "usr_historical",
                        "user_email": "private@example.test",
                        "rating": 4,
                        "comment": "A compelling watch.",
                        "date": datetime(2024, 3, 10, tzinfo=timezone.utc),
                    }
                ]
            ),
        }

    def __getitem__(self, name):
        return self.collections[name]


class Publisher:
    def __init__(self):
        self.events = []

    def is_healthy(self):
        return True

    async def publish(self, event):
        self.events.append(event)


@pytest.fixture
def integrated_services(monkeypatch):
    database = Database()
    publisher = Publisher()
    catalog_module.app.dependency_overrides[
        catalog_module.get_database
    ] = lambda: database
    interaction_module.app.dependency_overrides[
        interaction_module.get_publisher
    ] = lambda: publisher
    monkeypatch.setenv("CATALOG_SERVICE_URL", "http://catalog-service:8000")
    monkeypatch.setenv("INTERACTION_SERVICE_URL", "http://interaction-service:8000")
    monkeypatch.setenv(
        "RECOMMENDATION_SERVICE_URL", "http://recommendation-service:8000"
    )

    async def dispatch(request):
        if request.url.host == "catalog-service":
            service_app = catalog_module.app
        elif request.url.host == "interaction-service":
            service_app = interaction_module.app
        else:
            return httpx.Response(200, json={"status": "ok"})
        transport = ASGITransport(app=service_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url=f"http://{request.url.host}:8000",
        ) as service_client:
            return await service_client.request(
                request.method,
                request.url.path + f"?{request.url.query.decode()}"
                if request.url.query
                else request.url.path,
                content=request.content,
                headers={"content-type": request.headers.get("content-type", "")},
            )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(dispatch))
    gateway_app.dependency_overrides[get_http_client] = lambda: upstream
    yield database, publisher
    gateway_app.dependency_overrides.clear()
    catalog_module.app.dependency_overrides.clear()
    interaction_module.app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_gateway_reads_catalog_through_catalog_service(integrated_services):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=gateway_app), base_url="http://gateway"
    ) as client:
        response = await client.get(
            "/api/movies", params={"q": "Fish Tale", "genre": "Animation"}
        )

    assert response.status_code == 200
    assert response.json()["items"][0]["title"] == "A Fish Tale"


@pytest.mark.asyncio
async def test_gateway_review_request_is_published_by_interaction_service(
    integrated_services,
):
    _, publisher = integrated_services
    async with httpx.AsyncClient(
        transport=ASGITransport(app=gateway_app), base_url="http://gateway"
    ) as client:
        response = await client.post(
            "/api/interactions/reviews",
            json={
                "movie_id": str(MOVIE_ID),
                "user_id": "usr_integration",
                "rating": 5,
                "comment": "Excellent.",
            },
        )

    assert response.status_code == 202
    assert len(publisher.events) == 1
    assert publisher.events[0].payload.user_id == "usr_integration"
