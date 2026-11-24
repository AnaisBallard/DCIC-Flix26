#!/usr/bin/env python3
"""Print privacy-preserving structural statistics for the supplied dataset."""

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterator


MOVIE_FIELDS = (
    "_id", "title", "year", "genres", "poster", "plot", "fullplot",
    "imdb", "cast", "directors",
)
REVIEW_FIELDS = (
    "_id", "movie_id", "user_id", "rating", "comment", "date",
)


def read_records(path: Path) -> Iterator[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        first = ""
        while not first and (character := source.read(1)):
            if not character.isspace():
                first = character
        source.seek(0)

        if first == "[":
            records = json.load(source)
            for record in records:
                if isinstance(record, dict):
                    yield record
            return

        for line_number, line in enumerate(source, start=1):
            if line.strip():
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"{path.name}: JSON inválido en la línea {line_number}"
                    ) from error
                if isinstance(record, dict):
                    yield record


def type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def field_stats(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    result = {}
    for field in fields:
        types: Counter[str] = Counter()
        missing = null = 0
        for row in rows:
            if field not in row:
                missing += 1
            elif row[field] is None:
                null += 1
            else:
                types[type_name(row[field])] += 1
        result[field] = {
            "ausentes": missing,
            "nulos": null,
            "tipos": dict(sorted(types.items())),
        }
    return result


def object_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("$oid")
    return str(value) if value is not None else None


def profile(directory: Path) -> dict[str, Any]:
    movie_path = directory / "movies.json.gz"
    review_path = directory / "reviews.json.gz"
    for path in (movie_path, review_path):
        if not path.is_file():
            raise FileNotFoundError(f"No se encontró {path}")

    movies = list(read_records(movie_path))
    reviews = list(read_records(review_path))
    movie_ids = {
        identifier
        for row in movies
        if (identifier := object_id(row.get("_id"))) is not None
    }

    title_counts: Counter[str] = Counter()
    empty_titles = padded_titles = 0
    year_types: Counter[str] = Counter()
    for row in movies:
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            empty_titles += 1
        else:
            padded_titles += int(title != title.strip())
            title_counts[title.strip().casefold()] += 1

        year_types[
            "ausente" if "year" not in row
            else "nulo" if row["year"] is None
            else type_name(row["year"])
        ] += 1

    ratings: Counter[str] = Counter()
    missing_movie_id = orphan_movie_id = reviews_with_email = 0
    for row in reviews:
        if "rating" not in row:
            ratings["ausente"] += 1
        elif row["rating"] is None:
            ratings["nulo"] += 1
        elif isinstance(row["rating"], bool):
            ratings["bool"] += 1
        elif isinstance(row["rating"], (int, float)):
            ratings["numérico"] += 1
            ratings["fuera_de_1_a_5"] += int(
                row["rating"] < 1 or row["rating"] > 5
            )
        else:
            ratings["no_numérico"] += 1

        review_movie_id = object_id(row.get("movie_id"))
        if review_movie_id is None:
            missing_movie_id += 1
        elif review_movie_id not in movie_ids:
            orphan_movie_id += 1
        reviews_with_email += int("user_email" in row)

    return {
        "películas": {
            "documentos": len(movies),
            "campos": field_stats(movies, MOVIE_FIELDS),
            "títulos_vacíos_o_no_textuales": empty_titles,
            "títulos_con_espacios_en_los_extremos": padded_titles,
            "grupos_de_título_duplicado_tras_normalizar": sum(
                count > 1 for count in title_counts.values()
            ),
            "tipos_de_year": dict(sorted(year_types.items())),
        },
        "críticas": {
            "documentos": len(reviews),
            "campos": field_stats(reviews, REVIEW_FIELDS),
            "tipos_y_rango_de_rating": dict(sorted(ratings.items())),
            "movie_id_ausente": missing_movie_id,
            "referencias_a_películas_no_encontradas": orphan_movie_id,
            "documentos_con_campo_user_email": reviews_with_email,
        },
        "privacidad": (
            "No se imprimen valores de películas, textos de críticas, "
            "direcciones de correo ni identificadores."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directorio con movies.json.gz y reviews.json.gz",
    )
    arguments = parser.parse_args()
    print(json.dumps(profile(arguments.directory), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
