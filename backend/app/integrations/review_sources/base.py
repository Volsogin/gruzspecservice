"""Review sources: where reviews come from (seed file, manual JSON/CSV import; later — automatic sync).

We deliberately do NOT scrape Yandex/2GIS. A future source (official API/partner feed) only has
to implement `ReviewSource.fetch()`.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

ALLOWED_SOURCES = {"yandex", "2gis", "own"}


@dataclass(frozen=True)
class ReviewData:
    source: str
    external_id: str
    author: str
    rating: int
    text: str
    review_date: date
    vehicle_brand: str | None = None
    service_slug: str | None = None
    case_slug: str | None = None
    is_demo: bool = False


class ReviewSource(Protocol):
    name: str

    def fetch(self) -> list[ReviewData]: ...


def _parse(row: dict[str, Any], default_demo: bool) -> ReviewData:
    source = str(row.get("source", "own")).strip().lower()
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"unknown review source: {source}")
    rating = int(row["rating"])
    if not 1 <= rating <= 5:
        raise ValueError("rating must be 1..5")
    text = str(row["text"]).strip()
    author = str(row["author"]).strip()[:80]
    if not text or not author:
        raise ValueError("author and text are required")
    demo_raw = row.get("is_demo", default_demo)
    is_demo = demo_raw if isinstance(demo_raw, bool) else str(demo_raw).lower() in {"1", "true", "yes"}
    return ReviewData(
        source=source,
        external_id=str(row.get("external_id") or row.get("id") or f"{author}-{row['date']}")[:128],
        author=author,
        rating=rating,
        text=text,
        review_date=date.fromisoformat(str(row["date"])),
        vehicle_brand=row.get("vehicle_brand") or None,
        service_slug=row.get("service_slug") or None,
        case_slug=row.get("case_slug") or None,
        is_demo=is_demo,
    )


class JsonFileReviewSource:
    """Seed / manual import from a JSON array (see seeds/reviews.json for the format)."""

    name = "json"

    def __init__(self, path: Path, default_demo: bool = False) -> None:
        self.path = path
        self.default_demo = default_demo

    def fetch(self) -> list[ReviewData]:
        rows = json.loads(self.path.read_text(encoding="utf-8"))
        return [_parse(r, self.default_demo) for r in rows]


class CsvFileReviewSource:
    """Manual import from CSV with header: source,external_id,author,rating,text,date[,vehicle_brand,...]."""

    name = "csv"

    def __init__(self, path: Path, default_demo: bool = False) -> None:
        self.path = path
        self.default_demo = default_demo

    def fetch(self) -> list[ReviewData]:
        with self.path.open(encoding="utf-8", newline="") as fh:
            return [_parse(r, self.default_demo) for r in csv.DictReader(fh)]
