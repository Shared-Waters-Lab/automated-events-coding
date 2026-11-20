"""Tier 2: Wikidata.

For a place name this module:
  1. searches Wikidata labels and aliases (wbsearchentities),
  2. keeps a result only if the label/alias it matched produces the same
     lookup key as the query (the search API is prefix-based, so "Ili" would
     otherwise match "Ilim River"),
  3. keeps only items whose type is, or is a subclass of, a type allowed for
     the route (watercourse/lake/canal, or dam/reservoir),
  4. keeps only items located in one of the event's countries, when the event
     names any,
  5. walks downstream ("mouth of the watercourse", "lake outflow", and for dams
     "located in or next to body of water") until it reaches an item already
     known to belong to a basin.

All filters are exact or structural; there are no score thresholds.

Most property and item IDs below were confirmed against Wikidata; P201, Q12323,
Q131681 and Q12284 are from memory, so spot-check those on wikidata.org before
a large run (a wrong root type silently filters everything out).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from .cache import MISSING, JsonCache
from .normalize import Route, key_tiers, lookup_keys, search_forms

logger = logging.getLogger(__name__)

API_URL = "https://www.wikidata.org/w/api.php"

P_INSTANCE_OF = "P31"
P_SUBCLASS_OF = "P279"
P_COUNTRY = "P17"
P_ISO_ALPHA2 = "P297"
P_COORDINATES = "P625"
P_MOUTH = "P403"  # mouth of the watercourse
P_LAKE_OUTFLOW = "P201"
P_BODY_OF_WATER = "P206"  # located in or next to body of water (dams, reservoirs)
P_GEONAMES_ID = "P1566"

_KEPT_PROPS = (
    P_INSTANCE_OF, P_SUBCLASS_OF, P_COUNTRY, P_ISO_ALPHA2, P_COORDINATES,
    P_MOUTH, P_LAKE_OUTFLOW, P_BODY_OF_WATER, P_GEONAMES_ID,
)
DOWNSTREAM_PROPS = (P_MOUTH, P_LAKE_OUTFLOW, P_BODY_OF_WATER)

Q_WATERCOURSE = "Q355304"
Q_LAKE = "Q23397"
Q_CANAL = "Q12284"
Q_DAM = "Q12323"
Q_RESERVOIR = "Q131681"
Q_EARTH = "Q2"

ROOT_TYPES: dict[Route, frozenset[str]] = {
    Route.WATERCOURSE: frozenset({Q_WATERCOURSE, Q_LAKE, Q_CANAL}),
    Route.DAM: frozenset({Q_DAM, Q_RESERVOIR}),
}
ROOT_TYPES[Route.UNKNOWN] = ROOT_TYPES[Route.WATERCOURSE] | ROOT_TYPES[Route.DAM]

# Structural guards against cycles and bad edits, not accuracy settings.
_MAX_SUBCLASS_DEPTH = 15
_MAX_DOWNSTREAM_HOPS = 40
_ENTITIES_PER_REQUEST = 50  # API maximum

Transport = Callable[[dict], dict]


class WikidataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    qid: str
    label: str
    description: str


class HttpTransport:
    """Polite HTTP access to the Wikidata action API.

    Wikimedia asks for a descriptive User-Agent with contact details, and for
    bots to back off when the servers are lagged (the maxlag parameter).
    """

    def __init__(
        self,
        user_agent: str,
        *,
        url: str = API_URL,
        min_interval_s: float = 0.2,
        max_retries: int = 5,
        timeout_s: float = 30.0,
    ):
        import httpx  # installed with the openai client

        self._client = httpx.Client(headers={"User-Agent": user_agent}, timeout=timeout_s)
        self._httpx = httpx
        self._url = url
        self._min_interval = min_interval_s
        self._max_retries = max_retries
        self._last = 0.0

    def __call__(self, params: dict) -> dict:
        params = {**params, "format": "json", "maxlag": "5"}
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                resp = self._client.get(self._url, params=params)
            except self._httpx.TransportError as exc:
                last_error = exc
                time.sleep(min(2**attempt, 60))
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                last_error = WikidataError(f"HTTP {resp.status_code}")
                time.sleep(_retry_after(resp, attempt))
                continue
            if resp.status_code >= 400:
                raise WikidataError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise WikidataError("response was not JSON") from exc
            error = data.get("error")
            if error and error.get("code") == "maxlag":
                last_error = WikidataError("maxlag")
                time.sleep(_retry_after(resp, attempt))
                continue
            if error:
                raise WikidataError(f"{error.get('code')}: {error.get('info')}")
            return data
        raise WikidataError(f"giving up after {self._max_retries + 1} attempts") from last_error


def _retry_after(resp, attempt: int) -> float:
    try:
        return max(float(resp.headers.get("Retry-After", "")), 1.0)
    except ValueError:
        return float(min(2**attempt, 60))


def _trim_claims(claims: Mapping) -> dict[str, list]:
    """Keep only the properties we use, as plain values. Deprecated statements are dropped."""
    out: dict[str, list] = {}
    for prop in _KEPT_PROPS:
        values: list = []
        for statement in claims.get(prop, []):
            if statement.get("rank") == "deprecated":
                continue
            snak = statement.get("mainsnak", {})
            if snak.get("snaktype") != "value":
                continue
            value = snak.get("datavalue", {}).get("value")
            if prop == P_COORDINATES:
                if isinstance(value, dict) and str(value.get("globe", Q_EARTH)).endswith(Q_EARTH):
                    values.append([value["latitude"], value["longitude"]])
            elif isinstance(value, dict) and "id" in value:
                values.append(value["id"])
            elif isinstance(value, str):
                values.append(value)
        if values:
            out[prop] = values
    return out


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


class WikidataClient:
    def __init__(
        self,
        transport: Transport,
        cache: JsonCache | None = None,
        *,
        languages: Iterable[str] = ("en",),
        search_limit: int = 20,
    ):
        self._t = transport
        self._cache = cache or JsonCache()
        self._languages = tuple(languages)
        self._search_limit = search_limit
        self._reach_memo: dict[tuple[str, frozenset[str]], bool] = {}

    # ---- raw API access (cached) -------------------------------------------------

    def search(self, text: str, language: str) -> list[dict]:
        ns, key = f"search:{language}", text.strip().lower()
        cached = self._cache.get(ns, key)
        if cached is not MISSING:
            return cached
        data = self._t({
            "action": "wbsearchentities", "search": text, "language": language,
            "uselang": language, "type": "item", "limit": str(self._search_limit),
        })
        results = [
            {
                "id": r["id"],
                "label": r.get("label", ""),
                "description": r.get("description", ""),
                "match": (r.get("match") or {}).get("text") or r.get("label", ""),
            }
            for r in data.get("search", [])
            if "id" in r
        ]
        self._cache.set(ns, key, results)
        return results

    def claims(self, qids: Iterable[str]) -> dict[str, dict[str, list]]:
        wanted = list(dict.fromkeys(q for q in qids if q))
        out: dict[str, dict[str, list]] = {}
        missing: list[str] = []
        for q in wanted:
            cached = self._cache.get("claims", q)
            if cached is MISSING:
                missing.append(q)
            else:
                out[q] = cached
        for chunk in _chunks(missing, _ENTITIES_PER_REQUEST):
            data = self._t({"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims"})
            got = self._by_requested_id(data)
            for q in chunk:
                ent = got.get(q, {})
                trimmed = {} if "missing" in ent else _trim_claims(ent.get("claims", {}))
                self._cache.set("claims", q, trimmed)
                out[q] = trimmed
        return out

    def names(
        self, qids: Iterable[str], languages: Iterable[str] | None = None
    ) -> dict[str, list[list[str]]]:
        """All labels and aliases as [language, text] pairs (used at build time)."""
        langs = "|".join(languages) if languages else ""
        wanted = list(dict.fromkeys(q for q in qids if q))
        out: dict[str, list[list[str]]] = {}
        missing = []
        for q in wanted:
            cached = self._cache.get(f"names:{langs}", q)
            if cached is MISSING:
                missing.append(q)
            else:
                out[q] = cached
        for chunk in _chunks(missing, _ENTITIES_PER_REQUEST):
            params = {"action": "wbgetentities", "ids": "|".join(chunk), "props": "labels|aliases"}
            if langs:
                params["languages"] = langs
            got = self._by_requested_id(self._t(params))
            for q in chunk:
                ent = got.get(q, {})
                pairs = [[v["language"], v["value"]] for v in ent.get("labels", {}).values()]
                for vals in ent.get("aliases", {}).values():
                    pairs += [[v["language"], v["value"]] for v in vals]
                self._cache.set(f"names:{langs}", q, pairs)
                out[q] = pairs
        return out

    @staticmethod
    def _by_requested_id(data: dict) -> dict[str, dict]:
        got: dict[str, dict] = {}
        for eid, ent in data.get("entities", {}).items():
            got[eid] = ent
            redirect = ent.get("redirects") or {}
            if redirect.get("from"):
                got[redirect["from"]] = ent
        return got

    # ---- structure ---------------------------------------------------------------

    def is_instance_of(self, claims: Mapping[str, list], roots: frozenset[str]) -> bool:
        return any(self._type_reaches(t, roots) for t in claims.get(P_INSTANCE_OF, []))

    def _type_reaches(self, type_qid: str, roots: frozenset[str]) -> bool:
        memo_key = (type_qid, roots)
        if memo_key in self._reach_memo:
            return self._reach_memo[memo_key]
        frontier, seen, found = {type_qid}, {type_qid}, False
        for _ in range(_MAX_SUBCLASS_DEPTH):
            if frontier & roots:
                found = True
                break
            parents = self.claims(sorted(frontier))
            nxt = {p for q in frontier for p in parents.get(q, {}).get(P_SUBCLASS_OF, [])} - seen
            if not nxt:
                break
            seen |= nxt
            frontier = nxt
        self._reach_memo[memo_key] = found
        return found

    def iso2_codes(self, country_qids: Iterable[str]) -> frozenset[str]:
        qids = list(country_qids)
        claims = self.claims(qids)
        return frozenset(c.upper() for q in qids for c in claims.get(q, {}).get(P_ISO_ALPHA2, []))

    def find_candidates(self, name: str, route: Route, countries: frozenset[str]) -> list[Candidate]:
        """Items that match `name` exactly (by lookup key), have an allowed type,
        and, if `countries` is non-empty, lie in one of those countries.

        If some items match on the first key tier, items matching only on a
        looser tier are dropped.
        """
        tiers = [set(t) for t in key_tiers(name, query=True)]
        if not tiers:
            return []
        roots = ROOT_TYPES[route]
        texts = list(dict.fromkeys([name.strip(), *search_forms(name)]))

        for language in self._languages:
            for text in texts:
                matched: dict[str, tuple[int, dict]] = {}
                for r in self.search(text, language):
                    keys = set(lookup_keys(r["match"])) | set(lookup_keys(r["label"]))
                    tier = next((i for i, t in enumerate(tiers) if keys & t), None)
                    if tier is not None and (r["id"] not in matched or tier < matched[r["id"]][0]):
                        matched[r["id"]] = (tier, r)
                if not matched:
                    continue
                claims = self.claims(matched)
                accepted: list[tuple[int, Candidate]] = []
                for qid, (tier, r) in matched.items():
                    c = claims.get(qid, {})
                    if not self.is_instance_of(c, roots):
                        continue
                    if countries and not (self.iso2_codes(c.get(P_COUNTRY, [])) & countries):
                        continue
                    accepted.append((tier, Candidate(qid, r["label"], r["description"])))
                if accepted:
                    best = min(t for t, _ in accepted)
                    return [c for t, c in accepted if t == best]
        return []

    def walk_downstream(
        self, start: str, known: Mapping[str, frozenset[str]]
    ) -> tuple[frozenset[str], tuple[str, ...]]:
        """Follow the river graph from `start` until reaching items in `known`.

        Returns the basin codes reached and the known items that were hit.
        Branches (distributaries, multiple statements) are all followed.
        """
        bcodes: set[str] = set()
        hits: list[str] = []
        frontier, seen = [start], {start}
        for _ in range(_MAX_DOWNSTREAM_HOPS + 1):
            if not frontier:
                break
            to_expand = []
            for q in frontier:
                if q in known:
                    bcodes |= known[q]
                    hits.append(q)
                else:
                    to_expand.append(q)
            claims = self.claims(to_expand)
            nxt = []
            for q in to_expand:
                for prop in DOWNSTREAM_PROPS:
                    for target in claims.get(q, {}).get(prop, []):
                        if target not in seen:
                            seen.add(target)
                            nxt.append(target)
            frontier = nxt
        return frozenset(bcodes), tuple(hits)