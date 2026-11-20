"""Evidence produced by the lookup cascade for a single place name.

Each place name carries exactly one vote. A tier reports *findings* (a feature
it matched and the basins that feature points to); split_vote divides the one
vote equally across the matched features, then equally across each feature's
basins. Shares are Fractions so ties are exact and nothing depends on float
rounding.

Evidence has two strengths, and that is the only weighting in the system:
  STRONG  the name was tied to a basin through curated data or the river graph
          (dictionary/alias match, dam -> river -> dictionary, Wikidata chain)
  WEAK    the name was tied to a basin only by a coordinate falling inside a
          basin polygon
See voting.decide for how the two are combined.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction


class Strength(str, Enum):
    STRONG = "strong"
    WEAK = "weak"


@dataclass(frozen=True)
class Finding:
    """One feature a tier matched, and the basins it points to (may be empty)."""

    entity: str  # stable feature id used for de-duplication, e.g. "wd:Q1234", "gn:5678"
    bcodes: frozenset[str]
    source: str  # which tier produced it, e.g. "dictionary", "wikidata-chain", "geonames"
    detail: str = ""


@dataclass(frozen=True)
class Evidence:
    bcode: str
    share: Fraction  # this basin's share of the place name's single vote
    source: str
    entity: str
    detail: str = ""


@dataclass(frozen=True)
class Resolution:
    """Everything the cascade concluded about one place name."""

    placename: str
    route: str
    strength: Strength | None  # None: nothing usable found
    evidence: tuple[Evidence, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def entities(self) -> frozenset[str]:
        return frozenset(e.entity for e in self.evidence)


def split_vote(findings: Iterable[Finding]) -> tuple[Evidence, ...]:
    """Spread one vote over the findings for a single place name.

    Findings for the same entity are merged. An entity whose basin set is empty
    (for example, a point outside every basin polygon) still takes its share of
    the vote; that share is simply not cast for any basin.
    """
    merged: dict[str, Finding] = {}
    for f in findings:
        prev = merged.get(f.entity)
        merged[f.entity] = f if prev is None else Finding(
            prev.entity, prev.bcodes | f.bcodes, prev.source, prev.detail
        )
    if not merged:
        return ()
    n = len(merged)
    out: list[Evidence] = []
    for entity in sorted(merged):
        f = merged[entity]
        if not f.bcodes:
            continue
        share = Fraction(1, n * len(f.bcodes))
        out.extend(Evidence(b, share, f.source, entity, f.detail) for b in sorted(f.bcodes))
    return tuple(out)