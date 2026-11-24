from bson import ObjectId
from fastapi import HTTPException

from dcic_recommendation_app import main


class FakeCursor(list):
    def sort(self, *_args):
        return self


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    def find_one(self, query, *_args):
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ),
            None,
        )

    def find(self, query=None, *_args):
        query = query or {}
        if "user_id" in query:
            found = [
                document
                for document in self.documents
                if document.get("user_id") == query["user_id"]
            ]
        elif "source_movie_id" in query:
            source_ids = query["source_movie_id"]["$in"]
            found = [
                document
                for document in self.documents
                if document.get("source_movie_id") in source_ids
                and document.get("index_id") == query["index_id"]
            ]
        elif "_id" in query and isinstance(query["_id"], dict):
            movie_ids = query["_id"]["$in"]
            found = [
                document for document in self.documents if document.get("_id") in movie_ids
            ]
        else:
            found = list(self.documents)
        return FakeCursor(found)


class FakeDatabase:
    def __init__(self, collections):
        self.collections = collections

    def __getitem__(self, name):
        return self.collections[name]


def ready_database(*, reviews=(), neighbors=(), movies=()):
    fingerprint = "a" * 64
    cleaner_version = "1"
    index_id = main.make_index_id(fingerprint, cleaner_version)
    return FakeDatabase(
        {
            "_catalog_pipeline": FakeCollection(
                [
                    {
                        "_id": "catalog",
                        "cleaning_status": "ready",
                        "ready_event_status": "sent",
                        "source_fingerprint": fingerprint,
                        "cleaner_version": cleaner_version,
                    }
                ]
            ),
            "_recommendation_index_state": FakeCollection(
                [
                    {
                        "_id": "active",
                        "active_index_id": index_id,
                        "source_fingerprint": fingerprint,
                        "cleaner_version": cleaner_version,
                        "index_version": main.INDEX_VERSION,
                        "index_status": "ready",
                    }
                ]
            ),
            "reviews": FakeCollection(list(reviews)),
            "_recommendation_neighbors": FakeCollection(list(neighbors)),
            "movies": FakeCollection(list(movies)),
        }
    )


def test_personalized_recommendations_use_profile_ratings_and_exclude_rated_movies():
    liked_id = ObjectId("000000000000000000000001")
    rated_id = ObjectId("000000000000000000000002")
    recommended_id = ObjectId("000000000000000000000003")
    database = ready_database(
        reviews=[
            {"user_id": "usr_profile", "movie_id": liked_id, "rating": 5},
            {"user_id": "usr_profile", "movie_id": rated_id, "rating": 3},
            {"user_id": "another_profile", "movie_id": liked_id, "rating": 1},
        ],
        neighbors=[
            {
                "index_id": main.make_index_id("a" * 64, "1"),
                "source_movie_id": liked_id,
                "neighbors": [
                    {"movie_id": rated_id, "score": 1.0},
                    {"movie_id": recommended_id, "score": 0.75},
                ],
            }
        ],
        movies=[
            {"_id": rated_id, "title": "Already rated"},
            {"_id": recommended_id, "title": "For this profile"},
        ],
    )

    result = main.personalized_recommendations("usr_profile", database)

    assert result["total"] == 1
    assert result["items"][0]["_id"] == str(recommended_id)
    assert result["items"][0]["title"] == "For this profile"
    assert result["items"][0]["recommendation_score"] == 0.75


def test_personalized_recommendations_are_blocked_until_index_is_ready():
    database = ready_database()
    database.collections["_recommendation_index_state"] = FakeCollection([])

    try:
        main.personalized_recommendations("usr_profile", database)
    except HTTPException as error:
        assert error.status_code == 503
    else:
        raise AssertionError("Recommendations should require a ready index")


def test_similar_movies_use_precomputed_neighbors_and_return_not_found_for_missing_source():
    source_id = ObjectId("000000000000000000000001")
    similar_id = ObjectId("000000000000000000000002")
    index_id = main.make_index_id("a" * 64, "1")
    database = ready_database(
        neighbors=[
            {
                "index_id": index_id,
                "source_movie_id": source_id,
                "neighbors": [{"movie_id": similar_id, "score": 0.8}],
            }
        ],
        movies=[
            {"_id": source_id, "title": "Source"},
            {"_id": similar_id, "title": "Similar"},
        ],
    )

    result = main.similar_movies(str(source_id), database)

    assert result["total"] == 1
    assert result["items"][0]["title"] == "Similar"
    assert result["source_movie_id"] == str(source_id)

    try:
        main.similar_movies("000000000000000000000003", database)
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("Missing source movies should return 404")
