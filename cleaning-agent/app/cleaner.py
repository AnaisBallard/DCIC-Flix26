import copy
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from bson import ObjectId
from bson.decimal128 import Decimal128

SPAM_COMMENTS = {"", "...", "none", "null", "test"}
YEAR_PATTERN = re.compile(r"^\s*(\d{4})")
RUNTIME_PATTERN = re.compile(r"^\s*(-?\d+)")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal128):
        value = value.to_decimal()
    if not isinstance(value, (int, float, Decimal, str)):
        return None
    try:
        parsed = float(value.strip().replace(",", ".") if isinstance(value, str) else value)
    except (ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _normalize_year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        year = value
    elif isinstance(value, float) and value.is_integer():
        year = int(value)
    elif isinstance(value, str):
        match = YEAR_PATTERN.match(value)
        if not match:
            return None
        year = int(match.group(1))
    else:
        return None
    return year if 1888 <= year <= 2100 else None


def _normalize_runtime(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        runtime = value
    elif isinstance(value, float) and value.is_integer():
        runtime = int(value)
    elif isinstance(value, str):
        match = RUNTIME_PATTERN.match(value)
        if not match:
            return None
        runtime = int(match.group(1))
    else:
        return None
    return runtime if 0 < runtime <= 1000 else None


def _normalize_genres(value: Any) -> list[str] | None:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, list):
        values = [
            part
            for item in value
            for part in (item.split(",") if isinstance(item, str) else [])
        ]
    else:
        return None

    genres: list[str] = []
    seen: set[str] = set()
    for item in values:
        genre = item.strip()
        key = genre.casefold()
        if genre and key not in seen:
            genres.append(genre)
            seen.add(key)
    return genres


def normalize_movie(movie: dict[str, Any]) -> tuple[dict[str, Any], dict[str, tuple[Any, Any]]]:
    cleaned = copy.deepcopy(movie)
    changes: dict[str, tuple[Any, Any]] = {}

    def replace(field: str, value: Any, *, force: bool = False) -> None:
        old = cleaned.get(field)
        if old != value or force:
            cleaned[field] = value
            changes[field] = (old, value)

    title = cleaned.get("title")
    if isinstance(title, str):
        replace("title", title.strip())

    if "year" in cleaned and cleaned["year"] is not None:
        normalized_year = _normalize_year(cleaned["year"])
        if cleaned["year"] != normalized_year or (
            normalized_year is not None and type(cleaned["year"]) is not int
        ):
            replace(
                "year",
                normalized_year,
                force=normalized_year is not None and type(cleaned["year"]) is not int,
            )

    if "runtime" in cleaned and cleaned["runtime"] is not None:
        normalized_runtime = _normalize_runtime(cleaned["runtime"])
        if cleaned["runtime"] != normalized_runtime or (
            normalized_runtime is not None and type(cleaned["runtime"]) is not int
        ):
            replace(
                "runtime",
                normalized_runtime,
                force=normalized_runtime is not None
                and type(cleaned["runtime"]) is not int,
            )

    if "genres" in cleaned and cleaned["genres"] is not None:
        replace("genres", _normalize_genres(cleaned["genres"]))

    imdb = cleaned.get("imdb")
    if isinstance(imdb, dict) and imdb.get("rating") is not None:
        rating = _number(imdb["rating"])
        normalized = rating if rating is not None and 0 <= rating <= 10 else None
        if imdb["rating"] != normalized:
            old_imdb = copy.deepcopy(imdb)
            imdb["rating"] = normalized
            changes["imdb.rating"] = (old_imdb.get("rating"), normalized)

    return cleaned, changes


def normalize_review(review: dict[str, Any]) -> tuple[dict[str, Any], dict[str, tuple[Any, Any]]]:
    cleaned = copy.deepcopy(review)
    changes: dict[str, tuple[Any, Any]] = {}

    comment = cleaned.get("comment")
    if isinstance(comment, str):
        normalized_comment = comment.strip()
        if normalized_comment != comment:
            cleaned["comment"] = normalized_comment
            changes["comment"] = (comment, normalized_comment)

    raw_rating = cleaned.get("rating")
    rating_value = _number(raw_rating)
    normalized_rating = (
        int(rating_value)
        if rating_value is not None
        and rating_value.is_integer()
        and 1 <= rating_value <= 5
        else None
    )
    if raw_rating != normalized_rating or (
        normalized_rating is not None and type(raw_rating) is not int
    ):
        cleaned["rating"] = normalized_rating
        changes["rating"] = (raw_rating, normalized_rating)

    if "date" in cleaned and cleaned["date"] is not None:
        normalized_date = normalize_date(cleaned["date"])
        if normalized_date != cleaned["date"]:
            changes["date"] = (cleaned["date"], normalized_date)
            cleaned["date"] = normalized_date

    return cleaned, changes


def normalize_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if not math.isfinite(timestamp):
            return None
        if abs(timestamp) > 100_000_000_000:
            timestamp /= 1000
        try:
            parsed = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_spam_comment(value: Any) -> bool:
    return isinstance(value, str) and value.strip().casefold() in SPAM_COMMENTS


def movie_fingerprint(movie: dict[str, Any]) -> str:
    normalized, _ = normalize_movie(movie)
    normalized.pop("_id", None)
    canonical = json.dumps(
        _json_safe(normalized),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal128):
        return str(value.to_decimal())
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
