import importlib.util
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

service_main = Path(__file__).resolve().parents[1] / "app" / "main.py"
spec = importlib.util.spec_from_file_location(
    "dcic_interaction_unit_app", service_main
)
interaction_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(interaction_module)
app = interaction_module.app
get_publisher = interaction_module.get_publisher

MOVIE_ID = "573a13a4f29313caabd10527"


class Publisher:
    def __init__(self):
        self.events = []
        self.available = True

    def is_healthy(self):
        return self.available

    async def publish(self, event):
        self.events.append(event)


@pytest.fixture
def publisher():
    instance = Publisher()
    app.dependency_overrides[get_publisher] = lambda: instance
    yield instance
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_valid_review_is_published_without_database_access(publisher):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://interaction"
    ) as client:
        response = await client.post(
            "/interactions/reviews",
            json={
                "movie_id": MOVIE_ID,
                "user_id": "usr_test",
                "rating": 5,
                "comment": "Excellent film.",
            },
        )

    assert response.status_code == 202
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert str(event.event_id) == response.json()["event_id"]
    assert event.payload.movie_id == MOVIE_ID
    assert event.payload.rating == 5


@pytest.mark.asyncio
async def test_invalid_movie_id_or_rating_is_rejected(publisher):
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://interaction"
    ) as client:
        response = await client.post(
            "/interactions/reviews",
            json={
                "movie_id": "not-an-object-id",
                "user_id": "usr_test",
                "rating": 0,
                "comment": "Invalid.",
            },
        )

    assert response.status_code == 422
    assert publisher.events == []


@pytest.mark.asyncio
async def test_broker_failure_is_reported_and_not_accepted(publisher):
    async def fail(_event):
        raise RuntimeError("broker unavailable")

    publisher.publish = fail
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://interaction"
    ) as client:
        response = await client.post(
            "/interactions/reviews",
            json={
                "movie_id": MOVIE_ID,
                "user_id": "usr_test",
                "rating": 3,
                "comment": "Okay.",
            },
        )

    assert response.status_code == 503
