"""Find the service station coordinates via the 2GIS geocoder and write them into the seed.

    make geocode-sto                         # address from seeds/settings.json
    make geocode-sto ARGS='--address "г. Саратов, ул. Автокомбинатовская, 15"'
    make geocode-sto ARGS='--yes --db'       # no prompt, also update the `settings` row in the DB

The key is read from DGIS_API_KEY (.env) and is never printed. Results are shown first
(address, found object, coordinates, distance to Saratov centre) so you can check by eye
that the point is not in another city; nothing is written without confirmation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.db.models import Setting
from app.db.session import create_engine, create_session_factory
from app.domain.dispatch import haversine_km
from app.integrations.geocoder.dgis import DgisGeocoder, GeoResult
from app.services.site_settings import SARATOV_CENTER


def _print(results: list[GeoResult]) -> None:
    for i, r in enumerate(results, 1):
        km = haversine_km(SARATOV_CENTER[0], SARATOV_CENTER[1], r.lat, r.lon)
        print(f"  [{i}] {r.full_name}  ({r.type or '—'})")
        print(f"      lat={r.lat:.6f} lon={r.lon:.6f}  ~{km:.1f} км от центра Саратова")


async def _update_db(lat: float, lon: float, source: str) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    async with create_session_factory(engine)() as session:
        row = await session.scalar(select(Setting).where(Setting.key == "address"))
        if row is None:
            print("В БД нет настройки address — сначала выполните make seed")
        else:
            row.value = {**row.value, "lat": lat, "lon": lon, "coordinates_source": source}
            await session.commit()
            print("Обновлено в БД (settings.address).")
    await engine.dispose()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--address", help="адрес (по умолчанию — из seeds/settings.json)")
    parser.add_argument("--yes", action="store_true", help="не спрашивать подтверждение, взять первый результат")
    parser.add_argument("--db", action="store_true", help="также обновить настройку address в БД")
    args = parser.parse_args()

    settings = get_settings()
    seed_path: Path = settings.seeds_dir / "settings.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    address = args.address or seed["address"]["value"]["text"]

    if settings.dgis_api_key is None:
        print("DGIS_API_KEY не задан в .env — в seed остаётся плейсхолдер (центр Саратова).")
        return 1
    geocoder = DgisGeocoder(settings.dgis_api_key.get_secret_value(), settings.dgis_catalog_base)
    print(f"Ищем: {address}")
    try:
        results = await geocoder.geocode(address, limit=5)
    except UpstreamError as exc:
        print(f"Геокодер недоступен или ключ не подходит: {exc.message}. Плейсхолдер в seed не изменён.")
        return 1
    if not results:
        print("Ничего не найдено. Уточните адрес (--address).")
        return 1
    _print(results)

    choice = 1
    if not args.yes:
        answer = input("Записать координаты варианта № (Enter = 1, n = отмена): ").strip().lower()
        if answer in {"n", "no", "нет"}:
            print("Отменено, ничего не записано.")
            return 0
        choice = int(answer) if answer.isdigit() else 1
    picked = results[min(max(choice, 1), len(results)) - 1]

    source = f"2gis geocoder: {picked.full_name}"
    seed["address"]["value"].update(
        {"lat": round(picked.lat, 6), "lon": round(picked.lon, 6), "coordinates_source": source}
    )
    seed_path.write_text(json.dumps(seed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Записано в {seed_path.name}: lat={picked.lat:.6f} lon={picked.lon:.6f}")
    if args.db:
        await _update_db(round(picked.lat, 6), round(picked.lon, 6), source)
    else:
        print("Чтобы применить к уже заполненной БД: make geocode-sto ARGS='--db' или make seed ARGS=--force")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
