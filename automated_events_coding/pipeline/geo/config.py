"""Where the cascade's data lives, and which tiers are switched on.

Every path can be overridden with an environment variable. Any tier whose
data is missing is skipped with a warning, so the cascade can be rolled out
one tier at a time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_USER_AGENT = (
    "automated-events-coding/0.1 (set AEC_GEO_USER_AGENT to a name and contact address)"
)


def _env_path(name: str, default: Path | None) -> Path | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return Path(value) if value.strip() else None


@dataclass(frozen=True)
class GeoConfig:
    alias_table: Path | None = None
    gazetteer_db: Path | None = None
    basin_shapefile: Path | None = None
    basin_code_field: str = "BCODE"
    snap_km: float | None = None
    wikidata_enabled: bool = True
    wikidata_user_agent: str = DEFAULT_USER_AGENT
    wikidata_languages: tuple[str, ...] = ("en",)
    cache_path: Path | None = None

    @classmethod
    def from_env(cls, static_dir: Path) -> GeoConfig:
        snap = os.environ.get("AEC_GEO_SNAP_KM", "").strip()
        langs = os.environ.get("AEC_GEO_WIKIDATA_LANGUAGES", "en")
        return cls(
            alias_table=_env_path("AEC_GEO_ALIAS_TABLE", static_dir / "tributary_aliases.csv"),
            gazetteer_db=_env_path("AEC_GEO_GAZETTEER_DB", static_dir / "geo_gazetteer.sqlite"),
            # TODO: point this at the existing basin polygons.
            basin_shapefile=_env_path("AEC_GEO_BASIN_SHAPEFILE", None),
            basin_code_field=os.environ.get("AEC_GEO_BASIN_CODE_FIELD", "BCODE"),
            snap_km=float(snap) if snap else None,
            wikidata_enabled=os.environ.get("AEC_GEO_WIKIDATA", "1") not in ("0", "false", "no"),
            wikidata_user_agent=os.environ.get("AEC_GEO_USER_AGENT", DEFAULT_USER_AGENT),
            wikidata_languages=tuple(x.strip() for x in langs.split(",") if x.strip()),
            cache_path=_env_path(
                "AEC_GEO_CACHE", Path.home() / ".cache" / "automated_events_coding" / "geo_cache.sqlite"
            ),
        )