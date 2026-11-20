"""The lookup cascade for one non-country place name.

Tiers, in order. The first tier that produces STRONG evidence ends the search;
WEAK evidence accumulates across the remaining tiers.

  1   Tributary dictionary, exact keys (spreadsheet names, then imported aliases)   STRONG
  1b  Dam -> river: a uniquely matched GRanD dam whose river is in the dictionary   STRONG
  2   Wikidata: exact-match candidates walked downstream to a known item            STRONG
  3   Coordinates (Wikidata candidates, GeoNames, GRanD) -> basin polygons          WEAK

Every source is restricted to the event's countries when the event names any.
Not implemented yet: OSM/Overpass geometry (tier 4) and LLM-suggested names
verified by tiers 1-3 (tier 5).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from .config import DEFAULT_USER_AGENT, GeoConfig
from .dictionary import TributaryDictionary, load_alias_table
from .evidence import Finding, Resolution, Strength, split_vote
from .gazetteer import FEATURE_CODES, LocalGazetteer
from .normalize import Route, classify_route
from .spatial import BasinLocator
from .wikidata import P_COORDINATES, P_GEONAMES_ID, WikidataClient, WikidataError

logger = logging.getLogger(__name__)


@dataclass
class PlaceResolver:
    dictionary: TributaryDictionary
    gazetteer: LocalGazetteer | None = None
    locator: BasinLocator | None = None
    wikidata: WikidataClient | None = None
    _memo: dict = field(default_factory=dict, repr=False)

    # ---- construction --------------------------------------------------------------

    @classmethod
    def from_config(cls, config: GeoConfig, entries: Iterable[tuple[str, str]]) -> PlaceResolver:
        aliases = []
        if config.alias_table and config.alias_table.exists():
            aliases = load_alias_table(config.alias_table)
        else:
            logger.warning("No alias table at %s; tier 1 uses spreadsheet names only", config.alias_table)

        gazetteer = None
        if config.gazetteer_db and config.gazetteer_db.exists():
            gazetteer = LocalGazetteer(config.gazetteer_db)
        else:
            logger.warning("No gazetteer at %s; dam->river, country filtering and "
                           "GeoNames/GRanD points are disabled", config.gazetteer_db)

        locator = None
        if config.basin_shapefile and config.basin_shapefile.exists():
            locator = BasinLocator.from_file(
                config.basin_shapefile, config.basin_code_field, snap_km=config.snap_km
            )
        else:
            logger.warning("No basin shapefile configured (%s); point evidence is disabled",
                           config.basin_shapefile)

        wikidata = None
        if config.wikidata_enabled:
            from .cache import JsonCache
            from .wikidata import HttpTransport

            if config.wikidata_user_agent == DEFAULT_USER_AGENT:
                logger.warning("Using the default Wikidata User-Agent; set AEC_GEO_USER_AGENT "
                               "to include contact details, as Wikimedia's policy asks")
            wikidata = WikidataClient(
                HttpTransport(config.wikidata_user_agent),
                JsonCache(config.cache_path),
                languages=config.wikidata_languages,
            )

        return cls(TributaryDictionary(entries, aliases), gazetteer, locator, wikidata)

    # ---- public --------------------------------------------------------------------

    def countries_iso2(self, country_names: Iterable[str]) -> frozenset[str]:
        if self.gazetteer is None:
            return frozenset()
        out: set[str] = set()
        for name in country_names:
            codes = self.gazetteer.country_iso2(name)
            if not codes:
                logger.info("No ISO code for country %r; it won't restrict lookups", name)
            out |= codes
        return frozenset(out)

    def resolve(self, name: str, countries: frozenset[str] = frozenset()) -> Resolution:
        memo_key = (name, countries)
        if memo_key in self._memo:
            return self._memo[memo_key]
        resolution = self._resolve(name, countries)
        if not any(n.startswith("wikidata error") for n in resolution.notes):
            self._memo[memo_key] = resolution  # don't pin a transient network failure
        return resolution

    # ---- tiers ---------------------------------------------------------------------

    def _resolve(self, name: str, countries: frozenset[str]) -> Resolution:
        route = classify_route(name)
        notes: list[str] = []

        strong = self._tier1_dictionary(name)
        if not strong and self.gazetteer is not None and route is not Route.WATERCOURSE:
            strong = self._tier1b_dam_river(name, countries)

        points: list[tuple[str, tuple[tuple[float, float], ...], str, str]] = []
        covered_geonames: set[str] = set()
        if not strong and self.wikidata is not None:
            try:
                strong, points, covered_geonames = self._tier2_wikidata(name, route, countries)
            except WikidataError as exc:
                logger.warning("Wikidata lookup failed for %r: %s", name, exc)
                notes.append(f"wikidata error: {exc}")

        if strong:
            return Resolution(name, route.value, Strength.STRONG, split_vote(strong), tuple(notes))

        if self.gazetteer is not None:
            _, rows = self.gazetteer.find(
                name, feature_codes=FEATURE_CODES[route], countries=countries or None
            )
            for row in rows:
                if row.source == "geonames" and row.source_id in covered_geonames:
                    continue  # same feature as a Wikidata candidate
                points.append((row.entity, ((row.lat, row.lon),), row.source,
                               f"{row.name} [{row.feature_code}]"))

        if points and self.locator is None:
            notes.append(f"{len(points)} candidate point(s) ignored: no basin shapefile configured")
            points = []

        findings = []
        for entity, coords, source, detail in points:
            bcodes = frozenset(b for lat, lon in coords for b in self.locator.basins_at(lat=lat, lon=lon))
            if not bcodes:
                notes.append(f"{entity} lies outside every basin polygon")
            findings.append(Finding(entity, bcodes, source, detail))

        evidence = split_vote(findings)
        return Resolution(name, route.value, Strength.WEAK if evidence else None, evidence, tuple(notes))

    def _tier1_dictionary(self, name: str) -> list[Finding]:
        hit = self.dictionary.lookup(name)
        if hit is None:
            return []
        key, entries = hit
        return [Finding(e.entity, frozenset({e.bcode}), "dictionary", f"key {key!r} -> {e.canonical!r}")
                for e in entries]

    def _tier1b_dam_river(self, name: str, countries: frozenset[str]) -> list[Finding]:
        _, rows = self.gazetteer.find(
            name, feature_codes=frozenset({"DAM"}), countries=countries or None,
            sources=frozenset({"grand"}),
        )
        dams = {r.entity: r for r in rows}
        if len(dams) != 1:
            return []  # only follow a dam's river when the dam itself is unambiguous
        dam = next(iter(dams.values()))
        findings = []
        for river in dam.rivers:
            hit = self.dictionary.lookup(river)
            if hit:
                key, entries = hit
                findings += [Finding(e.entity, frozenset({e.bcode}), "dam-river",
                                     f"{dam.name!r} on {river!r} -> {e.canonical!r}") for e in entries]
        return findings

    def _tier2_wikidata(self, name: str, route: Route, countries: frozenset[str]):
        wd = self.wikidata
        candidates = wd.find_candidates(name, route, countries)
        if not candidates:
            return [], [], set()

        known = self.dictionary.qid_to_bcodes
        strong = []
        for c in candidates:
            bcodes, hits = wd.walk_downstream(c.qid, known)
            if bcodes:
                strong.append(Finding(f"wd:{c.qid}", bcodes, "wikidata-chain",
                                      f"{c.qid} {c.label!r} -> {', '.join(hits)}"))
        if strong:
            return strong, [], set()

        claims = wd.claims(c.qid for c in candidates)
        points, covered = [], set()
        for c in candidates:
            cl = claims.get(c.qid, {})
            covered |= set(cl.get(P_GEONAMES_ID, []))
            coords = tuple((float(lat), float(lon)) for lat, lon in cl.get(P_COORDINATES, []))
            if coords:
                points.append((f"wd:{c.qid}", coords, "wikidata-point", f"{c.qid} {c.label!r}"))
        return [], points, covered