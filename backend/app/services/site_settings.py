"""Site settings stored in the `settings` table (seeded from seeds/settings.json, editable in admin)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting
from app.domain.calculator import PricingRules
from app.domain.dispatch import DispatchConfig
from app.domain.worktime import work_status

DEFAULT_TZ = "Europe/Saratov"
# Fallback centre of Saratov — used only if the address coordinates were never set.
SARATOV_CENTER = (51.533557, 46.034257)


class SiteSettings:
    """Read-only snapshot of all settings with typed accessors."""

    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def section(self, key: str) -> dict[str, Any]:
        value = self.values.get(key)
        return value if isinstance(value, dict) else {}

    @property
    def timezone(self) -> str:
        return str(self.values.get("timezone") or DEFAULT_TZ)

    @property
    def consent_version(self) -> str:
        return str(self.section("legal").get("consent_version", "v1"))

    @property
    def company_name(self) -> str:
        return str(self.section("company").get("name", "ГРУЗСПЕЦСЕРВИС"))

    @property
    def sto_point(self) -> tuple[float, float]:
        addr = self.section("address")
        try:
            return float(addr["lat"]), float(addr["lon"])
        except (KeyError, TypeError, ValueError):
            return SARATOV_CENTER

    def dispatch_config(self) -> DispatchConfig:
        d = self.section("dispatch")
        lat, lon = self.sto_point
        polygon = tuple((float(p[0]), float(p[1])) for p in d.get("region_polygon") or [])
        radius = d.get("radius_km")
        return DispatchConfig(
            center_lat=lat,
            center_lon=lon,
            avg_speed_kmh=float(d.get("avg_speed_kmh", 30)),
            eta_minutes=int(d.get("eta_minutes", 30)),
            radius_km=float(radius) if radius is not None else None,
            region_name=str(d.get("region_name", "Саратовская область")),
            region_polygon=polygon,
        )

    def pricing_rules(self) -> PricingRules:
        p = self.section("pricing")
        defaults = PricingRules()
        return PricingRules(
            urgent_surcharge_pct=int(p.get("urgent_surcharge_pct", defaults.urgent_surcharge_pct)),
            onsite_fee=int(p.get("onsite_fee", defaults.onsite_fee)),
            round_to=max(1, int(p.get("round_to", defaults.round_to))),
            disclaimer=str(p.get("disclaimer", defaults.disclaimer)),
        )

    def work_status(self) -> dict[str, Any]:
        return work_status(self.section("work_hours"), self.timezone).as_dict()

    def public(self) -> dict[str, Any]:
        """Everything the website shows: contacts, address/coordinates, hours, stats, links."""
        lat, lon = self.sto_point
        address = {**self.section("address"), "lat": lat, "lon": lon}
        return {
            "company": self.section("company"),
            "contacts": self.section("contacts"),
            "messengers": self.section("messengers"),
            "address": address,
            "work_hours": self.section("work_hours"),
            "timezone": self.timezone,
            "stats": self.section("stats"),
            "warranty": self.section("warranty"),
            "advantages": self.values.get("advantages") or [],
            "review_links": self.section("review_links"),
            "dispatch": {
                "eta_minutes": self.dispatch_config().eta_minutes,
                "radius_km": self.dispatch_config().effective_radius_km,
                "note": self.section("dispatch").get("note"),
            },
            "consent": {"version": self.consent_version, "text": self.section("legal").get("consent_text")},
            "work_status": self.work_status(),
        }


async def load_settings(session: AsyncSession) -> SiteSettings:
    rows = (await session.execute(select(Setting.key, Setting.value))).all()
    return SiteSettings({key: value for key, value in rows})
