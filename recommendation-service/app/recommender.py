import hashlib
import math
import os
from collections import defaultdict
from typing import Any

import numpy as np
from pymongo import ReplaceOne
from sklearn.feature_extraction.text import TfidfVectorizer

INDEX_VERSION = os.getenv("RECOMMENDER_VERSION", "1")
MAX_FEATURES = 100_000
NEIGHBORS_PER_MOVIE = 30
MATRIX_BATCH_SIZE = 64
WRITE_BATCH_SIZE = 500


class IndexBuildError(RuntimeError):
    pass


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [
            item for item in value if isinstance(item, str) and item.strip()
        ]
    return []


def movie_text(movie: dict[str, Any]) -> str:
    title = _strings(movie.get("title"))
    genres = _strings(movie.get("genres"))
    if genres and len(genres) == 1 and "," in genres[0]:
        genres = [part.strip() for part in genres[0].split(",") if part.strip()]
    directors = _strings(movie.get("directors"))
    cast = _strings(movie.get("cast"))
    plot = _strings(movie.get("fullplot")) or _strings(movie.get("plot"))

    fields = [
        " ".join(title * 3),
        " ".join(f"genre_{genre}" for genre in genres for _ in range(2)),
        " ".join(f"director_{director}" for director in directors for _ in range(2)),
        " ".join(f"cast_{name}" for name in cast),
        " ".join(plot),
    ]
    return " ".join(field for field in fields if field).strip()


def make_index_id(source_fingerprint: str, cleaner_version: str) -> str:
    key = f"{source_fingerprint}|{cleaner_version}|{INDEX_VERSION}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_neighbor_documents(
    movies: list[dict[str, Any]],
    *,
    max_neighbors: int = NEIGHBORS_PER_MOVIE,
    batch_size: int = MATRIX_BATCH_SIZE,
) -> list[dict[str, Any]]:
    ordered_movies = sorted(movies, key=lambda movie: str(movie["_id"]))
    if not ordered_movies:
        raise IndexBuildError("Cannot build a recommendation index without movies")

    texts = [movie_text(movie) for movie in ordered_movies]
    try:
        matrix = TfidfVectorizer(
            max_features=MAX_FEATURES,
            ngram_range=(1, 2),
            sublinear_tf=True,
            dtype=np.float32,
        ).fit_transform(texts)
    except ValueError as error:
        raise IndexBuildError("Movie metadata produced no searchable terms") from error

    neighbors: list[dict[str, Any]] = []
    movie_ids = [movie["_id"] for movie in ordered_movies]
    for batch_start in range(0, len(ordered_movies), batch_size):
        batch_end = min(batch_start + batch_size, len(ordered_movies))
        similarities = (matrix[batch_start:batch_end] @ matrix.T).tocsr()
        for local_index in range(batch_end - batch_start):
            movie_index = batch_start + local_index
            start = similarities.indptr[local_index]
            end = similarities.indptr[local_index + 1]
            candidate_indices = similarities.indices[start:end]
            candidate_scores = similarities.data[start:end]
            valid = (candidate_indices != movie_index) & (candidate_scores > 0)
            candidate_indices = candidate_indices[valid]
            candidate_scores = candidate_scores[valid]

            if candidate_scores.size > max_neighbors:
                boundary = candidate_scores.size - max_neighbors
                threshold = np.partition(candidate_scores, boundary)[boundary]
                above_mask = candidate_scores > threshold
                above_indices = candidate_indices[above_mask]
                above_scores = candidate_scores[above_mask]
                tied = np.sort(candidate_indices[candidate_scores == threshold])
                tie_count = max_neighbors - above_indices.size
                candidate_indices = np.concatenate(
                    (above_indices, tied[:tie_count])
                )
                candidate_scores = np.concatenate(
                    (above_scores, np.full(tie_count, threshold, dtype=np.float32))
                )
            ranked = sorted(
                zip(candidate_indices.tolist(), candidate_scores.tolist()),
                key=lambda pair: (-float(pair[1]), str(movie_ids[pair[0]])),
            )
            neighbors.append(
                {
                    "_id": str(movie_ids[movie_index]),
                    "source_movie_id": movie_ids[movie_index],
                    "neighbors": [
                        {
                            "movie_id": movie_ids[index],
                            "score": float(score),
                        }
                        for index, score in ranked
                    ],
                }
            )
    return neighbors


def persist_neighbor_documents(collection, index_id: str, documents: list[dict[str, Any]]) -> None:
    for start in range(0, len(documents), WRITE_BATCH_SIZE):
        batch = documents[start : start + WRITE_BATCH_SIZE]
        operations = []
        for document in batch:
            indexed = {**document, "index_id": index_id}
            indexed["_id"] = f"{index_id}:{document['_id']}"
            operations.append(
                ReplaceOne({"_id": indexed["_id"]}, indexed, upsert=True)
            )
        if operations:
            collection.bulk_write(operations, ordered=False)


def rank_personalized_neighbors(
    ratings: dict[Any, int],
    neighbors_by_movie: dict[Any, list[dict[str, Any]]],
    *,
    limit: int,
) -> list[tuple[Any, float]]:
    rated_movie_ids = set(ratings)
    weighted_scores: defaultdict[Any, float] = defaultdict(float)
    total_preference = 0.0

    for movie_id, rating in ratings.items():
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            continue
        preference = (rating - 3) / 2.0
        if preference == 0:
            continue
        total_preference += abs(preference)
        for neighbor in neighbors_by_movie.get(movie_id, []):
            candidate_id = neighbor.get("movie_id")
            score = neighbor.get("score")
            if (
                candidate_id in rated_movie_ids
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                continue
            weighted_scores[candidate_id] += preference * float(score)

    if total_preference == 0:
        return []
    ranked = [
        (movie_id, score / total_preference)
        for movie_id, score in weighted_scores.items()
        if score > 0
    ]
    return sorted(ranked, key=lambda pair: (-pair[1], str(pair[0])))[:limit]
