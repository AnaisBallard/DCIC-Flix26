import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Iterator, TextIO

from bson import json_util
from pymongo import MongoClient, ReplaceOne
from pymongo.errors import OperationFailure

logger = logging.getLogger("dataset-loader")
BATCH_SIZE = 500


def ensure_user(database, username: str, password: str, role: str) -> None:
    roles = [{"role": role, "db": database.name}]
    try:
        database.command("updateUser", username, pwd=password, roles=roles)
    except OperationFailure as error:
        if error.code != 11:
            raise
        database.command(
            "createUser", username, pwd=password, roles=roles
        )


def ensure_database_access(client: MongoClient, database_name: str) -> None:
    database = client[database_name]
    cleaner_role = "catalogCleaner"
    cleaner_privileges = [
        {
            "resource": {"db": database_name, "collection": collection},
            "actions": ["find", "insert", "update", "remove"],
        }
        for collection in (
            "movies",
            "reviews",
            "_catalog_pipeline",
            "_cleaning_audit_details",
            "_cleaning_audit_runs",
        )
    ]
    try:
        database.command(
            "updateRole", cleaner_role, privileges=cleaner_privileges, roles=[]
        )
    except OperationFailure as error:
        if error.code != 11:
            raise
        database.command(
            "createRole",
            cleaner_role,
            privileges=cleaner_privileges,
            roles=[],
        )

    recommendation_role = "recommendationEngine"
    recommendation_privileges = [
        {
            "resource": {
                "db": database_name,
                "collection": "_recommendation_index_state",
            },
            "actions": ["find", "insert", "update", "remove", "findAndModify"],
        },
        {
            "resource": {
                "db": database_name,
                "collection": "_recommendation_neighbors",
            },
            "actions": ["find", "insert", "update", "remove"],
        },
    ]
    inherited_read_role = [{"role": "read", "db": database_name}]
    try:
        database.command(
            "updateRole",
            recommendation_role,
            privileges=recommendation_privileges,
            roles=inherited_read_role,
        )
    except OperationFailure as error:
        if error.code != 11:
            raise
        database.command(
            "createRole",
            recommendation_role,
            privileges=recommendation_privileges,
            roles=inherited_read_role,
        )

    for suffix, role in (
        ("CATALOG", "read"),
        ("RECOMMENDATION", recommendation_role),
        ("CONSUMER", "readWrite"),
        ("CLEANER", cleaner_role),
    ):
        username = os.environ[f"MONGODB_{suffix}_USER"]
        password = os.environ[f"MONGODB_{suffix}_PASSWORD"]
        ensure_user(database, username, password, role)

    database.movies.create_index("title")
    database.movies.create_index("year")
    database.reviews.create_index("movie_id")
    database.reviews.create_index("user_id")
    database.reviews.create_index([("movie_id", 1), ("user_id", 1)])
    database["_cleaning_audit_runs"].create_index([("started_at", -1)])
    database["_cleaning_audit_details"].create_index(
        [("run_id", 1), ("updated_at", 1)]
    )
    database["_recommendation_index_state"].update_one(
        {"_id": "active"},
        {
            "$setOnInsert": {
                "index_status": "waiting",
                "attempt": 0,
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
    database["_recommendation_neighbors"].create_index(
        [("index_id", 1), ("source_movie_id", 1)]
    )


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_dataset(path: Path) -> TextIO:
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig")
    return path.open("rt", encoding="utf-8-sig")


def documents_from(source: TextIO, path: Path) -> Iterator[Any]:
    first_character = source.read(1)
    while first_character and first_character.isspace():
        first_character = source.read(1)
    source.seek(0)

    if first_character == "[":
        documents = json_util.loads(source.read())
        if not isinstance(documents, list):
            raise ValueError(f"{path} must contain a JSON array")
        yield from documents
        return

    for line_number, line in enumerate(source, start=1):
        if line.strip():
            try:
                yield json_util.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid JSON in {path} at line {line_number}"
                ) from error


def collection_for(path: Path) -> str:
    name = path.name
    if name.endswith(".gz"):
        name = name[:-3]
    if not name.endswith(".json"):
        raise ValueError(f"Unsupported dataset file: {path.name}")
    return name[:-5]


def import_file(database, path: Path, *, force_reload: bool = False) -> None:
    collection_name = collection_for(path)
    checksum = file_digest(path)
    manifest = database["_dataset_imports"]
    import_id = f"{collection_name}:{path.name}"

    previous_import = manifest.find_one({"_id": import_id})
    if (
        not force_reload
        and previous_import
        and previous_import["sha256"] == checksum
    ):
        logger.info("Dataset %s is already loaded; skipping.", path.name)
        return

    collection = database[collection_name]
    batch = []
    imported_count = 0
    with open_dataset(path) as source:
        for document in documents_from(source, path):
            if not isinstance(document, dict) or "_id" not in document:
                raise ValueError(
                    f"Every document in {path.name} must have an _id"
                )
            batch.append(
                ReplaceOne({"_id": document["_id"]}, document, upsert=True)
            )
            if len(batch) == BATCH_SIZE:
                collection.bulk_write(batch, ordered=False)
                imported_count += len(batch)
                batch.clear()

    if batch:
        collection.bulk_write(batch, ordered=False)
        imported_count += len(batch)

    manifest.update_one(
        {"_id": import_id},
        {"$set": {"sha256": checksum, "documents": imported_count}},
        upsert=True,
    )
    logger.info(
        "Loaded %s documents from %s into %s.",
        imported_count,
        path.name,
        collection_name,
    )


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    dataset_directory = Path(os.getenv("DATASET_DIRECTORY", "/dataset"))
    files = sorted(
        path
        for path in dataset_directory.iterdir()
        if path.is_file()
        and (path.name.endswith(".json") or path.name.endswith(".json.gz"))
    )
    with MongoClient(
        os.environ["MONGODB_URI"], serverSelectionTimeoutMS=10000
    ) as client:
        client.admin.command("ping")
        database = client[os.environ["MONGODB_DATABASE"]]
        ensure_database_access(client, database.name)
        if not files:
            logger.warning(
                "No .json or .json.gz dataset files found in %s; "
                "no data was imported or cleaned.",
                dataset_directory,
            )
            database["_catalog_pipeline"].update_one(
                {"_id": "catalog"},
                {
                    "$set": {
                        "source_fingerprint": None,
                        "cleaner_version": os.getenv("CLEANER_VERSION", "1"),
                        "cleaning_status": "failed",
                        "ready_event_status": "pending",
                        "error_code": "dataset_missing",
                        "updated_at": datetime.now(timezone.utc),
                    },
                    "$unset": {
                        "lease_owner": "",
                        "lease_until": "",
                        "ready_event_id": "",
                        "run_id": "",
                        "completed_at": "",
                    },
                },
                upsert=True,
            )
            return

        dataset_fingerprint = hashlib.sha256(
            json.dumps(
                [
                    {"name": path.name, "sha256": file_digest(path)}
                    for path in files
                ],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        cleaner_version = os.getenv("CLEANER_VERSION", "1")
        pipeline_state = database["_catalog_pipeline"]
        previous_state = pipeline_state.find_one({"_id": "catalog"})
        pipeline_changed = (
            previous_state is None
            or previous_state.get("source_fingerprint") != dataset_fingerprint
            or previous_state.get("cleaner_version") != cleaner_version
        )
        force_reload = previous_state is not None and pipeline_changed

        for path in files:
            import_file(database, path, force_reload=force_reload)

        if pipeline_changed:
            now = datetime.now(timezone.utc)
            pipeline_state.update_one(
                {"_id": "catalog"},
                {
                    "$set": {
                        "source_fingerprint": dataset_fingerprint,
                        "cleaner_version": cleaner_version,
                        "cleaning_status": "pending",
                        "attempt": 0,
                        "ready_event_status": "pending",
                        "updated_at": now,
                        "error_code": None,
                    },
                    "$unset": {
                        "lease_owner": "",
                        "lease_until": "",
                        "next_retry_at": "",
                        "run_id": "",
                        "completed_at": "",
                    },
                },
                upsert=True,
            )
            logger.info(
                "Catalog pipeline queued for cleaning (source fingerprint %s).",
                dataset_fingerprint,
            )
        else:
            logger.info(
                "Catalog pipeline unchanged; preserving durable cleaning state."
            )


if __name__ == "__main__":
    main()
