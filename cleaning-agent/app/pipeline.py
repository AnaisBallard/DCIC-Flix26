import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from bson import ObjectId
from bson.decimal128 import Decimal128
from pymongo import ReplaceOne

from .cleaner import (
    is_spam_comment,
    movie_fingerprint,
    normalize_movie,
    normalize_review,
)
from .llm import InferredRating, infer_ratings, redact_comment

AUDIT_DETAILS = "_cleaning_audit_details"
AUDIT_RUNS = "_cleaning_audit_runs"
BATCH_SIZE = 500
LLM_BATCH_SIZE = 20


class CleaningError(RuntimeError):
    pass


def json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def _safe_snapshot(document: dict[str, Any], collection: str) -> dict[str, Any]:
    fields = (
        ("_id", "title", "year", "genres", "directors")
        if collection == "movies"
        else ("_id", "movie_id", "rating", "date")
    )
    return {
        field: json_safe(document[field])
        for field in fields
        if field in document
    }


def _record_detail(
    database,
    *,
    run_id: str,
    collection: str,
    document_id: Any,
    category: str,
    field: str,
    before: Any,
    after: Any,
    reason: str,
    method: str = "deterministic",
    evidence: dict[str, Any] | None = None,
) -> None:
    entity_id = str(document_id)
    key = f"{run_id}|{collection}|{entity_id}|{category}|{field}"
    detail_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
    database[AUDIT_DETAILS].update_one(
        {"_id": detail_id},
        {
            "$set": {
                "run_id": run_id,
                "collection": collection,
                "entity_id": entity_id,
                "category": category,
                "field": field,
                "before": json_safe(before),
                "after": json_safe(after),
                "reason": reason,
                "method": method,
                "evidence": json_safe(evidence or {}),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def _record_field_changes(
    database,
    *,
    run_id: str,
    collection: str,
    before: dict[str, Any],
    changes: dict[str, tuple[Any, Any]],
) -> None:
    for field, (old_value, new_value) in changes.items():
        category = f"{collection}.{field.replace('.', '_')}_normalized"
        if collection == "reviews" and field == "comment":
            old_value = redact_comment(old_value, max_length=None)
            new_value = redact_comment(new_value, max_length=None)
        _record_detail(
            database,
            run_id=run_id,
            collection=collection,
            document_id=before["_id"],
            category=category,
            field=field,
            before=old_value,
            after=new_value,
            reason="Normalized to the documented catalog contract.",
        )


def _content_key(movie: dict[str, Any]) -> str:
    return movie_fingerprint(movie)


def _review_quality(review: dict[str, Any]) -> tuple[float, bool, bool, str]:
    review_date = review.get("date")
    timestamp = (
        review_date.timestamp()
        if isinstance(review_date, datetime)
        else float("-inf")
    )
    rating_valid = isinstance(review.get("rating"), int) and not isinstance(
        review.get("rating"), bool
    )
    comment_valid = (
        isinstance(review.get("comment"), str)
        and not is_spam_comment(review["comment"])
    )
    return timestamp, rating_valid, comment_valid, str(review.get("_id", ""))


def _bulk_replace(collection, documents: list[dict[str, Any]]) -> None:
    for start in range(0, len(documents), BATCH_SIZE):
        batch = documents[start : start + BATCH_SIZE]
        if batch:
            collection.bulk_write(
                [
                    ReplaceOne({"_id": document["_id"]}, document, upsert=True)
                    for document in batch
                ],
                ordered=False,
            )


def _detail_metrics(database, run_id: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for detail in database[AUDIT_DETAILS].find(
        {"run_id": run_id}, {"category": 1}
    ):
        counts[detail["category"]] += 1
    return dict(sorted(counts.items()))


def run_cleaning(
    database,
    *,
    source_fingerprint: str,
    cleaner_version: str,
    infer: Callable[[list[str]], list[InferredRating]] = infer_ratings,
    heartbeat: Callable[[], None] = lambda: None,
) -> dict[str, Any]:
    run_id = hashlib.sha256(
        f"{source_fingerprint}|{cleaner_version}".encode("utf-8")
    ).hexdigest()
    started_at = datetime.now(timezone.utc)
    database[AUDIT_RUNS].update_one(
        {"_id": run_id},
        {
            "$set": {
                "source_fingerprint": source_fingerprint,
                "cleaner_version": cleaner_version,
                "status": "running",
                "started_at": started_at,
                "updated_at": started_at,
            }
        },
        upsert=True,
    )

    raw_movies = list(database["movies"].find({}))
    if not raw_movies:
        raise CleaningError("The catalog contains no movies")

    normalized_movies: list[dict[str, Any]] = []
    movies_by_fingerprint: dict[str, dict[str, Any]] = {}
    duplicate_movies: list[tuple[dict[str, Any], dict[str, Any]]] = []
    redirects: dict[str, Any] = {}

    for index, movie in enumerate(raw_movies):
        cleaned, changes = normalize_movie(movie)
        _record_field_changes(
            database,
            run_id=run_id,
            collection="movies",
            before=movie,
            changes=changes,
        )
        key = _content_key(cleaned)
        original = movies_by_fingerprint.get(key)
        if original is None:
            movies_by_fingerprint[key] = cleaned
            normalized_movies.append(cleaned)
        else:
            canonical, duplicate = sorted(
                (original, cleaned), key=lambda item: str(item["_id"])
            )
            if canonical is not original:
                movies_by_fingerprint[key] = canonical
                normalized_movies[normalized_movies.index(original)] = canonical
            duplicate_movies.append((canonical, duplicate))
            redirects[str(duplicate["_id"])] = canonical["_id"]
            _record_detail(
                database,
                run_id=run_id,
                collection="movies",
                document_id=duplicate["_id"],
                category="movies.duplicate_removed",
                field="_id",
                before=_safe_snapshot(duplicate, "movies"),
                after={"_id": str(canonical["_id"])},
                reason="Exact duplicate after normalization; references are redirected to the retained record.",
            )
        if index % BATCH_SIZE == 0:
            heartbeat()

    movie_ids = {str(movie["_id"]) for movie in normalized_movies}
    raw_reviews = list(database["reviews"].find({}))
    kept_reviews: list[dict[str, Any]] = []
    removed_reviews: list[Any] = []
    review_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for index, review in enumerate(raw_reviews):
        cleaned, changes = normalize_review(review)
        _record_field_changes(
            database,
            run_id=run_id,
            collection="reviews",
            before=review,
            changes=changes,
        )

        movie_id = cleaned.get("movie_id")
        redirected_id = redirects.get(str(movie_id))
        if redirected_id is not None:
            cleaned["movie_id"] = redirected_id
            _record_detail(
                database,
                run_id=run_id,
                collection="reviews",
                document_id=review["_id"],
                category="reviews.movie_reference_updated",
                field="movie_id",
                before=movie_id,
                after=redirected_id,
                reason="Updated reference to the retained duplicate movie.",
            )
            movie_id = redirected_id

        if movie_id is None or str(movie_id) not in movie_ids:
            removed_reviews.append(review["_id"])
            _record_detail(
                database,
                run_id=run_id,
                collection="reviews",
                document_id=review["_id"],
                category="reviews.orphan_removed",
                field="record",
                before=_safe_snapshot(review, "reviews"),
                after=None,
                reason="The referenced movie is absent from the cleaned catalog.",
            )
            continue

        if is_spam_comment(cleaned.get("comment")):
            removed_reviews.append(review["_id"])
            _record_detail(
                database,
                run_id=run_id,
                collection="reviews",
                document_id=review["_id"],
                category="reviews.spam_removed",
                field="comment",
                before=cleaned.get("comment"),
                after=None,
                reason="Comment exactly matches a configured empty/spam marker.",
            )
            continue

        user_id = cleaned.get("user_id")
        if isinstance(user_id, str) and user_id.strip():
            review_groups[(str(movie_id), user_id.strip())].append(cleaned)
        else:
            kept_reviews.append(cleaned)
        if index % BATCH_SIZE == 0:
            heartbeat()

    for grouped_reviews in review_groups.values():
        if len(grouped_reviews) == 1:
            kept_reviews.append(grouped_reviews[0])
            continue
        winner = max(grouped_reviews, key=_review_quality)
        kept_reviews.append(winner)
        for duplicate in grouped_reviews:
            if duplicate is winner:
                continue
            removed_reviews.append(duplicate["_id"])
            _record_detail(
                database,
                run_id=run_id,
                collection="reviews",
                document_id=duplicate["_id"],
                category="reviews.duplicate_removed",
                field="record",
                before=_safe_snapshot(duplicate, "reviews"),
                after={"_id": str(winner["_id"])},
                reason="Kept the most recent review for this user/movie pair; ties prefer a valid rating and comment.",
            )

    pending_inference: list[dict[str, Any]] = []
    for review in kept_reviews:
        if review.get("rating") is not None:
            continue
        if isinstance(review.get("comment"), str) and review["comment"].strip():
            pending_inference.append(review)
            continue
        _record_detail(
            database,
            run_id=run_id,
            collection="reviews",
            document_id=review["_id"],
            category="reviews.rating_unresolved_no_text",
            field="rating",
            before=None,
            after=None,
            reason="No usable comment is available to infer the missing rating.",
        )

    for start in range(0, len(pending_inference), LLM_BATCH_SIZE):
        batch = pending_inference[start : start + LLM_BATCH_SIZE]
        inferred = infer([review["comment"] for review in batch])
        if len(inferred) != len(batch):
            raise CleaningError("LLM result count did not match the input batch")
        for review, result in zip(batch, inferred):
            if result.rating is None:
                _record_detail(
                    database,
                    run_id=run_id,
                    collection="reviews",
                    document_id=review["_id"],
                    category="reviews.rating_unresolved",
                    field="rating",
                    before=None,
                    after=None,
                    reason="The model confidence was below the acceptance threshold.",
                    method="openai",
                    evidence={"confidence": result.confidence, "reason": result.reason},
                )
                continue
            review["rating"] = result.rating
            _record_detail(
                database,
                run_id=run_id,
                collection="reviews",
                document_id=review["_id"],
                category="reviews.rating_inferred",
                field="rating",
                before=None,
                after=result.rating,
                reason="Inferred from review sentiment by the configured LLM.",
                method="openai",
                evidence={"confidence": result.confidence, "reason": result.reason},
            )
        heartbeat()

    _bulk_replace(database["movies"], normalized_movies)
    _bulk_replace(database["reviews"], kept_reviews)
    if removed_reviews:
        database["reviews"].delete_many({"_id": {"$in": removed_reviews}})
    if duplicate_movies:
        database["movies"].delete_many(
            {"_id": {"$in": [duplicate["_id"] for _, duplicate in duplicate_movies]}}
        )

    metrics = _detail_metrics(database, run_id)
    completed_at = datetime.now(timezone.utc)
    summary = {
        "_id": run_id,
        "run_id": run_id,
        "source_fingerprint": source_fingerprint,
        "cleaner_version": cleaner_version,
        "status": "ready",
        "started_at": started_at,
        "completed_at": completed_at,
        "metrics": metrics,
        "movies_examined": len(raw_movies),
        "reviews_examined": len(raw_reviews),
        "llm_inferences": metrics.get("reviews.rating_inferred", 0),
        "llm_unresolved": metrics.get("reviews.rating_unresolved", 0),
        "unresolved_ratings": (
            metrics.get("reviews.rating_unresolved", 0)
            + metrics.get("reviews.rating_unresolved_no_text", 0)
        ),
    }
    database[AUDIT_RUNS].replace_one({"_id": run_id}, summary, upsert=True)
    return summary
