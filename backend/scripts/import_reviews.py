"""Manual review import from JSON or CSV (`make import-reviews FILE=path`). Upserts by (source, external_id)."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.integrations.review_sources.base import CsvFileReviewSource, JsonFileReviewSource, ReviewSource
from app.services.reviews import import_reviews


async def main(path: Path) -> None:
    source: ReviewSource = CsvFileReviewSource(path) if path.suffix.lower() == ".csv" else JsonFileReviewSource(path)
    engine = create_engine(get_settings().database_url)
    async with create_session_factory(engine)() as session:
        result = await import_reviews(session, source)
        await session.commit()
    await engine.dispose()
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    asyncio.run(main(parser.parse_args().file))
