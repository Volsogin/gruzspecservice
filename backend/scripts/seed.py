"""Load seed data: `make seed` (insert missing) or `make seed ARGS=--force` (overwrite seeded content)."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.config import get_settings
from app.db.session import create_engine, create_session_factory
from app.integrations.storage.base import LocalStorage
from app.seeding import run_seed


async def main(force: bool) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    storage = LocalStorage(settings.media_dir, settings.media_url_prefix, settings.api_base_url)
    async with factory() as session:
        result = await run_seed(session, settings.seeds_dir, storage, force=force)
        await session.commit()
    await engine.dispose()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite seeded rows")
    asyncio.run(main(parser.parse_args().force))
