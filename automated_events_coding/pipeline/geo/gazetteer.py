"""Local point gazetteer (GeoNames hydrography + GRanD dams) in one SQLite file.

Built once by `build_assets gazetteer`; queried at run time by exact lookup
key, feature code, country and source. Also holds a country-name -> ISO
alpha-2 table (from GeoNames country features and countryInfo.txt), which the
cascade uses to restrict every source to the event's countries.
"""

from __future__ import annotations

import csv
import logging
import math
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .normalize import Route, key_tiers, lookup_keys

logger = logging.getLogger(__name__)

# GeoNames feature codes (class H) used for each route.
FEATURE_CODES: dict[Route, frozenset[str]] = {
    Route.WATERCOURSE: frozenset({
        "STM", "STMI", "STMS", "STMX", "WAD", "WADS", "CNL", "CNLI", "CNLD", "LK", "LKI", "LKS",
    }),
    Route.DAM: frozenset({"DAM", "RSV", "RSVI"}),
}
FEATURE_CODES[Route.UNKNOWN] = FEATURE_CODES[Route.WATERCOURSE] | FEATURE_CODES[Route.DAM]

# GeoNames political-entity codes, used only to harvest country names.
COUNTRY_FEATURE_CODES = frozenset({"PCLI", "PCLD", "PCLF", "PCLS", "PCLIX", "PCL"})

GEONAMES_COLUMNS = [
    "geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
    "feature_class", "feature_code", "country_code", "cc2", "admin1_code", "admin2_code",
    "admin3_code", "admin4_code", "population", "elevation", "dem", "timezone", "modification_date",
]

# Default GRanD v1.3 attribute names; override in load_grand if your copy differs.
GRAND_COLUMNS = {
    "id": "GRAND_ID", "dam_name": "DAM_NAME", "alt_name": "ALT_NAME", "res_name": "RES_NAME",
    "river": "RIVER", "alt_river": "ALT_RIVER", "country": "COUNTRY",
    "lat": "LAT_DD", "lon": "LONG_DD",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    key TEXT NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT,
    lat REAL NOT NULL, lon REAL NOT NULL, country TEXT, feature_code TEXT, rivers TEXT,
    PRIMARY KEY (key, source, source_id)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS countries (
    key TEXT NOT NULL, iso2 TEXT NOT NULL, PRIMARY KEY (key, iso2)
) WITHOUT ROWID;
"""


@dataclass(frozen=True)
class PlaceRow:
    source: str
    source_id: str
    name: str
    lat: float
    lon: float
    countries: frozenset[str]
    feature_code: str
    rivers: tuple[str, ...]

    @property
    def entity(self) -> str:
        prefix = {"geonames": "gn"}.get(self.source, self.source)
        return f"{prefix}:{self.source_id}"


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


class LocalGazetteer:
    """Read-only access to the built gazetteer."""

    def __init__(self, path: str | Path):
        self._conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)

    def find(
        self,
        name: str,
        *,
        feature_codes: frozenset[str] | None = None,
        countries: frozenset[str] | None = None,
        sources: frozenset[str] | None = None,
    ) -> tuple[str | None, list[PlaceRow]]:
        """Rows for the first key tier that has any rows passing the filters."""
        for keys in key_tiers(name, query=True):
            found: dict[tuple[str, str], PlaceRow] = {}
            for key in keys:
                for src, sid, nm, lat, lon, ctry, fc, rivers in self._conn.execute(
                    "SELECT source, source_id, name, lat, lon, country, feature_code, rivers"
                    " FROM places WHERE key = ?", (key,)
                ):
                    row = PlaceRow(src, sid, nm, lat, lon,
                                   frozenset(c for c in (ctry or "").split("|") if c),
                                   fc or "", tuple(r for r in (rivers or "").split("|") if r))
                    if feature_codes is not None and row.feature_code not in feature_codes:
                        continue
                    if countries and not row.countries & countries:
                        continue
                    if sources is not None and row.source not in sources:
                        continue
                    found.setdefault((src, sid), row)
            if found:
                return " | ".join(keys), [found[k] for k in sorted(found)]
        return None, []

    def country_iso2(self, name: str) -> frozenset[str]:
        for key in lookup_keys(name):
            codes = [c for (c,) in self._conn.execute("SELECT iso2 FROM countries WHERE key = ?", (key,))]
            if codes:
                return frozenset(codes)
        return frozenset()


class GazetteerWriter:
    """Builds the gazetteer file. Use as a context manager."""

    def __init__(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(_SCHEMA)
        self._places: list[tuple] = []
        self._countries: list[tuple] = []

    def __enter__(self) -> GazetteerWriter:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def add_place(self, *, source: str, source_id, name: str, lat: float, lon: float,
                  countries: Iterable[str], feature_code: str, names: Iterable[str],
                  rivers: Iterable[str] = ()) -> None:
        keys = {k for n in names for k in lookup_keys(n)}
        country = "|".join(sorted({c.upper() for c in countries if c}))
        river = "|".join(r for r in dict.fromkeys(rivers) if r)
        self._places.extend(
            (k, source, str(source_id), name, float(lat), float(lon), country, feature_code, river)
            for k in keys
        )
        if len(self._places) >= 100_000:
            self.flush()

    def add_country(self, names: Iterable[str], iso2: str) -> None:
        if not iso2:
            return
        self._countries.extend((k, iso2.upper()) for n in names for k in lookup_keys(n))

    def country_iso2(self, name: str) -> frozenset[str]:
        self.flush()
        for key in lookup_keys(name):
            codes = [c for (c,) in self._conn.execute("SELECT iso2 FROM countries WHERE key = ?", (key,))]
            if codes:
                return frozenset(codes)
        return frozenset()

    def flush(self) -> None:
        if self._places:
            self._conn.executemany("INSERT OR IGNORE INTO places VALUES (?,?,?,?,?,?,?,?,?)", self._places)
            self._places.clear()
        if self._countries:
            self._conn.executemany("INSERT OR IGNORE INTO countries VALUES (?,?)", self._countries)
            self._countries.clear()
        self._conn.commit()

    def close(self) -> None:
        self.flush()
        self._conn.execute("ANALYZE")
        self._conn.commit()
        self._conn.close()


def load_country_info(writer: GazetteerWriter, path: str | Path) -> int:
    """GeoNames countryInfo.txt: tab-separated, '#'-prefixed header lines."""
    n = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            iso2, iso3, name = cols[0], cols[1], cols[4]
            writer.add_country([name, iso3, iso2], iso2)
            n += 1
    return n


def load_geonames(writer: GazetteerWriter, path: str | Path, *, chunksize: int = 250_000) -> int:
    """allCountries.txt/.zip (or a single-country file) from download.geonames.org/export/dump."""
    wanted = FEATURE_CODES[Route.UNKNOWN] | COUNTRY_FEATURE_CODES
    reader = pd.read_csv(
        path, sep="\t", header=None, names=GEONAMES_COLUMNS, dtype=str,
        quoting=csv.QUOTE_NONE, na_filter=False, chunksize=chunksize, encoding="utf-8",
        usecols=["geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
                 "feature_code", "country_code"],
    )
    n = 0
    for chunk in reader:
        chunk = chunk[chunk["feature_code"].isin(wanted)]
        for row in chunk.itertuples(index=False):
            names = [row.name, row.asciiname, *row.alternatenames.split(",")]
            if row.feature_code in COUNTRY_FEATURE_CODES:
                writer.add_country(names, row.country_code)
                continue
            writer.add_place(
                source="geonames", source_id=row.geonameid, name=row.name,
                lat=float(row.latitude), lon=float(row.longitude),
                countries=[row.country_code], feature_code=row.feature_code, names=names,
            )
            n += 1
    writer.flush()
    return n


def load_grand(
    writer: GazetteerWriter,
    path: str | Path,
    *,
    columns: dict[str, str] = GRAND_COLUMNS,
    country_lookup: Callable[[str], frozenset[str]] | None = None,
) -> int:
    """GRanD dams (shapefile or any format geopandas reads). Load countries first."""
    import geopandas as gpd

    lookup = country_lookup or writer.country_iso2
    gdf = gpd.read_file(path)
    n, unmapped = 0, set()
    for _, row in gdf.iterrows():
        names = [_clean(row.get(columns["dam_name"])), _clean(row.get(columns["alt_name"])),
                 _clean(row.get(columns["res_name"]))]
        names = [part.strip() for n_ in names for part in n_.split(";") if part.strip()]
        if not names:
            continue
        lat, lon = row.get(columns["lat"]), row.get(columns["lon"])
        if lat is None or lon is None or pd.isna(lat) or pd.isna(lon):
            if row.geometry is None:
                continue
            lat, lon = row.geometry.y, row.geometry.x
        country_name = _clean(row.get(columns["country"]))
        codes = lookup(country_name) if country_name else frozenset()
        if country_name and not codes:
            unmapped.add(country_name)
        writer.add_place(
            source="grand", source_id=_clean(row.get(columns["id"])) or str(n),
            name=names[0], lat=float(lat), lon=float(lon), countries=codes,
            feature_code="DAM", names=names,
            rivers=[_clean(row.get(columns["river"])), _clean(row.get(columns["alt_river"]))],
        )
        n += 1
    if unmapped:
        logger.warning("GRanD: %d country names had no ISO code: %s", len(unmapped), sorted(unmapped))
    writer.flush()
    return n