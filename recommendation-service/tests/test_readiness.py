import hashlib

from dcic_recommendation_app import main as recommendation_module


def test_recommendations_wait_for_catalog_ready_event_and_matching_index():
    fingerprint = "a" * 64
    cleaner_version = "1"
    catalog = {
        "cleaning_status": "ready",
        "ready_event_status": "sent",
        "source_fingerprint": fingerprint,
        "cleaner_version": cleaner_version,
    }

    waiting = recommendation_module.recommendation_status(catalog, None)
    assert waiting["status"] == "indexing"
    assert waiting["recommendations_available"] is False

    index_id = recommendation_module.make_index_id(fingerprint, cleaner_version)
    ready = recommendation_module.recommendation_status(
        catalog,
        {
            "active_index_id": index_id,
            "source_fingerprint": fingerprint,
            "cleaner_version": cleaner_version,
            "index_version": recommendation_module.INDEX_VERSION,
            "index_status": "ready",
        },
    )
    assert ready["status"] == "ready"
    assert ready["recommendations_available"] is True


def test_recommendations_wait_until_catalog_ready_event_is_confirmed():
    state = {
        "cleaning_status": "ready",
        "ready_event_status": "pending",
        "source_fingerprint": "a" * 64,
        "cleaner_version": "1",
    }

    status = recommendation_module.recommendation_status(state, None)

    assert status["status"] == "waiting"
    assert status["recommendations_available"] is False


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
