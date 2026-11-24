import asyncio
import os
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

SERVICE_URLS = {
    "catalog": "CATALOG_SERVICE_URL",
    "interaction": "INTERACTION_SERVICE_URL",
    "recommendation": "RECOMMENDATION_SERVICE_URL",
    "consumer": "CONSUMER_SERVICE_URL",
    "cleaning": "CLEANING_AGENT_URL",
}
DEFAULT_SERVICE_URLS = {
    "catalog": "http://catalog-service:8000",
    "interaction": "http://interaction-service:8000",
    "recommendation": "http://recommendation-service:8000",
    "consumer": "http://consumer:8000",
    "cleaning": "http://cleaning-agent:8000",
}
OBJECT_ID_PATTERN = r"^[a-fA-F0-9]{24}$"
RUN_ID_PATTERN = r"^[a-f0-9]{64}$"
MovieId = Annotated[str, Path(pattern=OBJECT_ID_PATTERN)]


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    movie_id: str = Field(pattern=OBJECT_ID_PATTERN)
    user_id: str = Field(min_length=1, max_length=128)
    rating: int = Field(strict=True, ge=1, le=5)
    comment: str = Field(min_length=1, max_length=5000)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="DCIC-Flix26 Gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Accept"],
)


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def service_url(name: str) -> str:
    return os.getenv(SERVICE_URLS[name], DEFAULT_SERVICE_URLS[name]).rstrip("/")


async def forward(
    client: httpx.AsyncClient,
    service: str,
    path: str,
    *,
    method: str = "GET",
    params: dict[str, Any] | None = None,
    payload: BaseModel | None = None,
) -> Response:
    try:
        upstream = await client.request(
            method,
            f"{service_url(service)}{path}",
            params=(
                {key: value for key, value in params.items() if value is not None}
                if params is not None
                else None
            ),
            json=payload.model_dump(mode="json") if payload is not None else None,
        )
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504, detail=f"{service} service timed out"
        ) from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503, detail=f"{service} service is unavailable"
        ) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=503, detail=f"{service} service returned an error"
        ) from error

    content_type = upstream.headers.get("content-type", "application/json")
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"content-type": content_type},
    )


async def service_payload(
    client: httpx.AsyncClient, service: str, path: str
) -> dict[str, Any]:
    try:
        response = await client.get(f"{service_url(service)}{path}")
        response.raise_for_status()
        payload = response.json()
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504, detail=f"{service} service timed out"
        ) from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=503, detail=f"{service} service is unavailable"
        ) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=503, detail=f"{service} service returned an error"
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=502, detail=f"{service} service returned invalid JSON"
        ) from error
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502, detail=f"{service} service returned an invalid response"
        )
    return payload


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "gateway"}


@app.get("/api/health")
async def system_health(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> JSONResponse:
    async def check(name: str) -> tuple[str, str]:
        try:
            response = await client.get(
                f"{service_url(name)}/health", timeout=2.0
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("status") != "ok":
                return name, "unhealthy"
            return name, "ok"
        except (httpx.HTTPError, ValueError):
            return name, "unavailable"

    checks = dict(await asyncio.gather(*(check(name) for name in SERVICE_URLS)))
    healthy = all(status == "ok" for status in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "services": checks,
        },
    )


@app.get("/api/status")
async def system_status(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> dict[str, Any]:
    async def read_status(service: str, path: str) -> dict[str, Any]:
        try:
            return await service_payload(client, service, path)
        except HTTPException:
            if service == "cleaning":
                return {
                    "cleaning_status": "failed",
                    "source_fingerprint": None,
                    "cleaner_version": None,
                    "updated_at": None,
                    "error_code": "status_unavailable",
                }
            return {
                "status": "failed",
                "source_fingerprint": None,
                "recommendations_available": False,
            }

    catalog, recommendations = await asyncio.gather(
        read_status("cleaning", "/status"),
        read_status("recommendation", "/status"),
    )
    cleaning_status = catalog.get("cleaning_status", "failed")
    recommendation_status = recommendations.get("status", "failed")
    catalog_ready = cleaning_status == "ready"
    recommendations_ready = (
        catalog_ready
        and recommendation_status == "ready"
        and recommendations.get("recommendations_available") is True
    )
    return {
        "catalog": catalog,
        "recommendations": recommendations,
        "capabilities": {
            "browse": True,
            "reviews": catalog_ready,
            "recommendations": recommendations_ready,
        },
    }


@app.get("/api/audit/runs")
async def audit_runs(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    return await forward(
        client,
        "cleaning",
        "/audit/runs",
        params={"limit": limit, "offset": offset},
    )


@app.get("/api/audit/runs/{run_id}/details")
async def audit_run_details(
    run_id: Annotated[str, Path(pattern=RUN_ID_PATTERN)],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Response:
    return await forward(
        client,
        "cleaning",
        f"/audit/runs/{run_id}/details",
        params={"limit": limit, "offset": offset},
    )


@app.get("/api/movies")
async def list_movies(
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    q: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
    genre: Annotated[str | None, Query(min_length=1, max_length=60)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Response:
    return await forward(
        client,
        "catalog",
        "/movies",
        params={"q": q, "genre": genre, "page": page, "page_size": page_size},
    )


@app.get("/api/movies/{movie_id}")
async def movie_details(
    movie_id: MovieId,
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> Response:
    return await forward(client, "catalog", f"/movies/{movie_id}")


@app.get("/api/movies/{movie_id}/reviews")
async def movie_reviews(
    movie_id: MovieId,
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Response:
    return await forward(
        client,
        "catalog",
        f"/movies/{movie_id}/reviews",
        params={"page": page, "page_size": page_size},
    )


@app.post("/api/interactions/reviews", status_code=202)
async def create_review(
    review: ReviewInput,
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> Response:
    catalog_status = await service_payload(client, "cleaning", "/status")
    if catalog_status.get("cleaning_status") != "ready":
        raise HTTPException(
            status_code=503,
            detail="Reviews are unavailable until catalog cleaning is ready",
        )
    return await forward(
        client,
        "interaction",
        "/interactions/reviews",
        method="POST",
        payload=review,
    )
