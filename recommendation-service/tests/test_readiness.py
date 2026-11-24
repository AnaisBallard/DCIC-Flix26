import hashlib
import importlib.util
from pathlib import Path

import pytest

main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
spec = importlib.util.spec_from_file_location("dcic_recommendation_readiness", main_path)
recommendation_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recommendation_module)


@pytest.mark.asyncio
async def test_catalog_event_moves_service_to_indexing_not_ready():
    readiness = recommendation_module.RecommendationReadiness()
    recommendation_module.app.state.readiness = readiness

    waiting = await recommendation_module.status()
    assert waiting["status"] == "waiting"
    assert waiting["recommendations_available"] is False

    readiness.catalog_ready_event("a" * 64)
    indexing = await recommendation_module.status()
    assert indexing["status"] == "indexing"
    assert indexing["source_fingerprint"] == "a" * 64
    assert indexing["recommendations_available"] is False


def test_catalog_ready_event_requires_matching_deterministic_id():
    fingerprint = "a" * 64
    version = "1"
    event_id = hashlib.sha256(
        f"catalog.cleaning.completed|{fingerprint}|{version}".encode("utf-8")
    ).hexdigest()
    event = {
        "event_id": event_id,
        "event_type": "catalog.cleaning.completed",
        "source_fingerprint": fingerprint,
        "cleaner_version": version,
    }

    assert recommendation_module.is_valid_catalog_ready_event(event)
    assert not recommendation_module.is_valid_catalog_ready_event(
        {**event, "event_id": "0" * 64}
    )
