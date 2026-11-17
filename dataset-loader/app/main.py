import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
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
    for suffix, role in (
        ("CATALOG", "read"),
        ("RECOMMENDATION", "read"),
        ("CONSUMER", "readWrite"),
    ):
        username = os.environ[f"MONGODB_{suffix}_USER"]
        password = os.environ[f"MONGODB_{suffix}_PASSWORD"]
        ensure_user(database, username, password, role)

    database.movies.create_index("title")
    database.movies.create_index("year")
    database.reviews.create_index("movie_id")
    database.reviews.create_index("user_id")
    database.reviews.create_index([("movie_id", 1), ("user_id", 1)])


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


def import_file(database, path: Path) -> None:
    collection_name = collection_for(path)
    checksum = file_digest(path)
    manifest = database["_dataset_imports"]
    import_id = f"{collection_name}:{path.name}"

    previous_import = manifest.find_one({"_id": import_id})
    if previous_import and previous_import["sha256"] == checksum:
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
            return
        for path in files:
            import_file(database, path)


if __name__ == "__main__":
    main()
