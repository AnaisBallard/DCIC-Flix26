from bson import ObjectId
import pytest

from dcic_recommendation_app.recommender import (
    build_neighbor_documents,
    make_index_id,
    movie_text,
    rank_personalized_neighbors,
)


def test_movie_text_weights_and_includes_multiple_content_fields():
    text = movie_text(
        {
            "title": "The Quiet Planet",
            "genres": ["Science Fiction"],
            "directors": ["Ada Director"],
            "cast": ["Sam Actor"],
            "plot": "A lone pilot explores a distant world.",
        }
    )

    assert "The Quiet Planet" in text
    assert "genre_Science Fiction" in text
    assert "director_Ada Director" in text
    assert "cast_Sam Actor" in text
    assert "distant world" in text


def test_neighbor_index_is_precomputed_sorted_and_excludes_self():
    movie_ids = [ObjectId(f"{index:024x}") for index in range(1, 5)]
    movies = [
        {
            "_id": movie_ids[0],
            "title": "Solar Voyage",
            "genres": ["Science Fiction"],
            "plot": "An astronaut explores a distant planet.",
        },
        {
            "_id": movie_ids[1],
            "title": "Voyage to Mars",
            "genres": ["Science Fiction"],
            "plot": "An astronaut explores a distant planet.",
        },
        {
            "_id": movie_ids[2],
            "title": "Paris at Dawn",
            "genres": ["Romance"],
            "plot": "Two strangers meet and fall in love in Paris.",
        },
        {
            "_id": movie_ids[3],
            "title": "The Last Laugh",
            "genres": ["Comedy"],
            "plot": "A comedian tries to save a small theatre.",
        },
    ]

    documents = build_neighbor_documents(movies, max_neighbors=2, batch_size=2)
    by_id = {document["source_movie_id"]: document for document in documents}

    assert len(documents) == len(movies)
    assert by_id[movie_ids[0]]["neighbors"][0]["movie_id"] == movie_ids[1]
    assert all(
        neighbor["movie_id"] != document["source_movie_id"]
        for document in documents
        for neighbor in document["neighbors"]
    )
    assert all(len(document["neighbors"]) <= 2 for document in documents)


def test_personalized_ranking_combines_likes_and_dislikes_without_watched_films():
    liked = "liked"
    disliked = "disliked"
    already_watched = "watched"
    candidate_a = "candidate-a"
    candidate_b = "candidate-b"
    ratings = {liked: 5, disliked: 1, already_watched: 4, "neutral": 3}
    neighbors = {
        liked: [
            {"movie_id": candidate_a, "score": 0.9},
            {"movie_id": already_watched, "score": 1.0},
        ],
        disliked: [{"movie_id": candidate_a, "score": 0.8}],
        already_watched: [{"movie_id": candidate_b, "score": 0.6}],
    }

    ranked = rank_personalized_neighbors(ratings, neighbors, limit=10)

    assert [movie_id for movie_id, _ in ranked] == [candidate_b, candidate_a]
    assert [score for _, score in ranked] == pytest.approx([0.12, 0.04])
    assert all(movie_id not in ratings for movie_id, _ in ranked)
    assert rank_personalized_neighbors({"neutral": 3}, neighbors, limit=10) == []


def test_index_id_changes_when_source_or_cleaner_version_changes():
    fingerprint = "a" * 64

    assert make_index_id(fingerprint, "1") != make_index_id(fingerprint, "2")
    assert make_index_id(fingerprint, "1") != make_index_id("b" * 64, "1")
