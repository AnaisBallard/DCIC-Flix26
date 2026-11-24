import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cleaner import is_spam_comment, normalize_movie, normalize_review
from app.llm import InferredRating, LLMConfigurationError, infer_ratings, redact_comment
from app.main import CLEANER_VERSION, _claim_run
from app.pipeline import run_cleaning


def test_movie_and_review_normalization_handles_profiled_anomalies():
    movie, movie_changes = normalize_movie(
        {
            "_id": "movie",
            "title": "  A Film  ",
            "year": "2001 (US)",
            "runtime": "-90 min",
            "genres": "Drama, drama, Comedy",
            "imdb": {"rating": "12.5", "votes": 15},
        }
    )
    review, review_changes = normalize_review(
        {"_id": "review", "rating": "6", "comment": " text ", "date": "invalid"}
    )

    assert movie["title"] == "A Film"
    assert movie["year"] == 2001
    assert movie["runtime"] is None
    assert movie["genres"] == ["Drama", "Comedy"]
    assert movie["imdb"] == {"rating": None, "votes": 15}
    assert review["rating"] is None
    assert review["comment"] == "text"
    assert review["date"] is None
    assert {"year", "runtime", "genres", "imdb.rating"} <= movie_changes.keys()
    assert {"rating", "comment", "date"} <= review_changes.keys()


def test_spam_match_is_exact_after_whitespace_and_case_normalization():
    assert is_spam_comment("  TeSt ")
    assert not is_spam_comment("This was a test of the film")


def test_normalized_integer_fields_are_stored_as_integers():
    movie, movie_changes = normalize_movie(
        {"_id": "movie", "year": 2001.0, "runtime": 120.0}
    )
    review, review_changes = normalize_review({"_id": "review", "rating": 4.0})

    assert type(movie["year"]) is int
    assert type(movie["runtime"]) is int
    assert type(review["rating"]) is int
    assert {"year", "runtime"} <= movie_changes.keys()
    assert "rating" in review_changes


def test_llm_receives_redacted_text_and_rejects_low_confidence(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    seen_payloads = []

    def respond(request):
        seen_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "results": [
                                        {
                                            "rating": 5,
                                            "confidence": 0.9,
                                            "reason": "Positive sentiment",
                                        },
                                        {
                                            "rating": 3,
                                            "confidence": 0.2,
                                            "reason": "Unclear opinion",
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        results = infer_ratings(
            [
                "Great film, reach me at ana@example.org or +1 415-555-0100",
                "https://example.test/review",
            ],
            client=client,
        )

    assert results == [
        InferredRating(5, 0.9, "Positive sentiment"),
        InferredRating(None, 0.2, "Unclear opinion"),
    ]
    serialized = json.dumps(seen_payloads)
    assert "ana@example.org" not in serialized
    assert "415-555-0100" not in serialized
    assert "https://example.test/review" not in serialized
    assert "[redacted email]" in serialized
    assert "[redacted phone]" in serialized
    assert "[redacted URL]" in serialized
    assert "[redacted email]" in redact_comment("ana@example.org")


def test_llm_missing_key_fails_explicitly_without_network(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(LLMConfigurationError):
        infer_ratings(["A review with ambiguous sentiment"])


class Cursor:
    def __init__(self, documents):
        self.documents = documents

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self, documents=()):
        self.documents = {document["_id"]: document for document in documents}

    def find(self, filters, projection=None):
        documents = [
            document
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in filters.items())
        ]
        if projection:
            included = {key for key, value in projection.items() if value}
            excluded = {key for key, value in projection.items() if not value}
            if included:
                documents = [
                    {key: value for key, value in document.items() if key in included}
                    for document in documents
                ]
            elif excluded:
                documents = [
                    {key: value for key, value in document.items() if key not in excluded}
                    for document in documents
                ]
        return Cursor(documents)

    def update_one(self, filters, update, upsert=False):
        key = filters["_id"]
        document = self.documents.get(key)
        if document is None and upsert:
            document = {"_id": key}
            self.documents[key] = document
        if document is not None:
            document.update(update.get("$setOnInsert", {}) if key not in self.documents else {})
            document.update(update.get("$set", {}))

    def bulk_write(self, operations, ordered=False):
        for operation in operations:
            replacement = operation._doc
            self.documents[replacement["_id"]] = replacement

    def delete_many(self, filters):
        ids = filters["_id"]["$in"]
        for document_id in ids:
            self.documents.pop(document_id, None)

    def replace_one(self, filters, replacement, upsert=False):
        self.documents[filters["_id"]] = replacement


class Database:
    def __init__(self, movies, reviews):
        self.collections = {
            "movies": Collection(movies),
            "reviews": Collection(reviews),
            "_cleaning_audit_details": Collection(),
            "_cleaning_audit_runs": Collection(),
        }

    def __getitem__(self, name):
        return self.collections[name]


def test_pipeline_audits_changes_redirects_duplicates_and_redacts_identity():
    from bson import ObjectId

    canonical_id = ObjectId("000000000000000000000001")
    duplicate_id = ObjectId("000000000000000000000002")
    missing_movie_id = ObjectId("000000000000000000000099")
    movies = [
        {
            "_id": canonical_id,
            "title": "  A Film",
            "year": "2001 (US)",
            "genres": "Drama, drama",
        },
        {
            "_id": duplicate_id,
            "title": "A Film",
            "year": 2001,
            "genres": ["Drama"],
        },
    ]
    reviews = [
        {
            "_id": ObjectId("000000000000000000000011"),
            "movie_id": duplicate_id,
            "user_id": "user-one",
            "user_email": "private@example.test",
            "rating": None,
            "comment": "older duplicate",
            "date": "2024-01-01",
        },
        {
            "_id": ObjectId("000000000000000000000012"),
            "movie_id": canonical_id,
            "user_id": "user-one",
            "user_email": "private@example.test",
            "rating": 4,
            "comment": "newer duplicate",
            "date": "2024-02-01",
        },
        {
            "_id": ObjectId("000000000000000000000013"),
            "movie_id": canonical_id,
            "user_id": "user-two",
            "user_email": "private@example.test",
            "rating": None,
            "comment": "A wonderful film",
            "date": "2024-03-01",
        },
        {
            "_id": ObjectId("000000000000000000000014"),
            "movie_id": canonical_id,
            "user_id": "user-three",
            "rating": 4,
            "comment": "test",
            "date": "2024-03-01",
        },
        {
            "_id": ObjectId("000000000000000000000015"),
            "movie_id": missing_movie_id,
            "user_id": "user-four",
            "rating": 4,
            "comment": "orphan",
            "date": "2024-03-01",
        },
        {
            "_id": ObjectId("000000000000000000000016"),
            "movie_id": canonical_id,
            "user_id": "user-five",
            "rating": None,
        },
    ]
    database = Database(movies, reviews)
    inference_inputs = []

    def infer(comments):
        inference_inputs.extend(comments)
        return [InferredRating(5, 0.9, "Clearly positive")]

    summary = run_cleaning(
        database,
        source_fingerprint="a" * 64,
        cleaner_version="test",
        infer=infer,
    )

    cleaned_movies = list(database["movies"].documents.values())
    cleaned_reviews = list(database["reviews"].documents.values())
    details = list(database["_cleaning_audit_details"].documents.values())
    serialized_details = json.dumps(details, default=str)

    assert len(cleaned_movies) == 1
    assert cleaned_movies[0]["_id"] == canonical_id
    assert len(cleaned_reviews) == 3
    assert {str(review["movie_id"]) for review in cleaned_reviews} == {str(canonical_id)}
    inferred_review = next(review for review in cleaned_reviews if review["user_id"] == "user-two")
    assert inferred_review["rating"] == 5
    assert inference_inputs == ["A wonderful film"]
    assert summary["status"] == "ready"
    assert summary["metrics"]["movies.duplicate_removed"] == 1
    assert summary["metrics"]["reviews.spam_removed"] == 1
    assert summary["metrics"]["reviews.orphan_removed"] == 1
    assert summary["metrics"]["reviews.duplicate_removed"] == 1
    assert summary["metrics"]["reviews.rating_inferred"] == 1
    assert summary["metrics"]["reviews.rating_unresolved_no_text"] == 1
    assert summary["unresolved_ratings"] == 1
    assert "private@example.test" not in serialized_details
    assert "user_email" not in serialized_details
    assert "user_id" not in serialized_details


class PipelineStateCollection:
    def __init__(self, state):
        self.state = state

    def find_one(self, _filters):
        return dict(self.state)

    def find_one_and_update(self, _filters, update, return_document=None):
        now = update["$set"]["updated_at"]
        lease_until = self.state.get("lease_until")
        if self.state["cleaning_status"] == "running" and lease_until > now:
            return None
        self.state.update(update["$set"])
        self.state["attempt"] += update["$inc"]["attempt"]
        self.state.pop("next_retry_at", None)
        return dict(self.state)


class PipelineStateDatabase:
    def __init__(self, state):
        self.collection = PipelineStateCollection(state)

    def __getitem__(self, _name):
        return self.collection


def test_pipeline_lease_prevents_parallel_claims_and_recovers_expired_work():
    from datetime import datetime, timedelta, timezone

    database = PipelineStateDatabase(
        {
            "_id": "catalog",
            "source_fingerprint": "a" * 64,
            "cleaner_version": CLEANER_VERSION,
            "cleaning_status": "pending",
            "attempt": 0,
        }
    )

    first_claim = _claim_run(database, "worker-one")
    assert first_claim["cleaning_status"] == "running"
    assert first_claim["attempt"] == 1
    assert _claim_run(database, "worker-two") is None

    database.collection.state["lease_until"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    recovered_claim = _claim_run(database, "worker-two")
    assert recovered_claim["lease_owner"] == "worker-two"
    assert recovered_claim["attempt"] == 2
