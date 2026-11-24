import importlib.util
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

service_main = Path(__file__).resolve().parents[1] / "app" / "main.py"
spec = importlib.util.spec_from_file_location("dcic_gateway_unit_app", service_main)
gateway_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway_module)
app = gateway_module.app
get_http_client = gateway_module.get_http_client

MOVIE_ID = "573a13a4f29313caabd10527"


@pytest.fixture(autouse=True)
def clear_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


async def request_with_upstream(method, url, **kwargs):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"url": str(request.url), "method": request.method},
        )
    )
    async with httpx.AsyncClient(transport=transport) as upstream:
        app.dependency_overrides[get_http_client] = lambda: upstream
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            return await client.request(method, url, **kwargs)


@pytest.mark.asyncio
async def test_movie_search_is_forwarded_with_validated_filters():
    response = await request_with_upstream(
        "GET", "/api/movies", params={"q": "Fish Tale", "genre": "Animation"}
    )

    assert response.status_code == 200
    upstream_url = response.json()["url"]
    assert "q=Fish+Tale" in upstream_url
    assert "genre=Animation" in upstream_url


@pytest.mark.asyncio
async def test_optional_filters_are_omitted_when_not_provided():
    response = await request_with_upstream("GET", "/api/movies", params={"q": "fish"})

    assert response.status_code == 200
    upstream_url = response.json()["url"]
    assert "q=fish" in upstream_url
    assert "genre=" not in upstream_url


@pytest.mark.asyncio
async def test_invalid_movie_id_is_rejected_before_forwarding():
    response = await request_with_upstream("GET", "/api/movies/not-an-object-id")

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_rating_is_rejected_before_forwarding():
    response = await request_with_upstream(
        "POST",
        "/api/interactions/reviews",
        json={
            "movie_id": MOVIE_ID,
            "user_id": "usr_test",
            "rating": 6,
            "comment": "Review",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_review_submission_is_blocked_until_catalog_is_ready():
    def respond(request):
        return httpx.Response(
            200,
            json={"cleaning_status": "running"},
        )

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as upstream:
        app.dependency_overrides[get_http_client] = lambda: upstream
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.post(
                "/api/interactions/reviews",
                json={
                    "movie_id": MOVIE_ID,
                    "user_id": "usr_test",
                    "rating": 5,
                    "comment": "Review",
                },
            )

    assert response.status_code == 503
    assert "until catalog cleaning is ready" in response.json()["detail"]


@pytest.mark.asyncio
async def test_business_status_keeps_browsing_when_recommendations_are_unavailable():
    def respond(request):
        if request.url.host == "cleaning-agent":
            return httpx.Response(200, json={"cleaning_status": "ready"})
        return httpx.Response(503, json={"detail": "offline"})

    transport = httpx.MockTransport(respond)
    async with httpx.AsyncClient(transport=transport) as upstream:
        app.dependency_overrides[get_http_client] = lambda: upstream
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["capabilities"] == {
        "browse": True,
        "reviews": True,
        "recommendations": False,
    }


@pytest.mark.asyncio
async def test_upstream_connection_failure_is_reported_as_unavailable():
    transport = httpx.MockTransport(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline"))
    )
    async with httpx.AsyncClient(transport=transport) as upstream:
        app.dependency_overrides[get_http_client] = lambda: upstream
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/api/movies")

    assert response.status_code == 503
    assert response.json()["detail"] == "catalog service is unavailable"


@pytest.mark.asyncio
async def test_global_health_reports_degraded_upstream():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200 if "catalog" in str(request.url) else 503,
            json={"status": "ok"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as upstream:
        app.dependency_overrides[get_http_client] = lambda: upstream
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            response = await client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
