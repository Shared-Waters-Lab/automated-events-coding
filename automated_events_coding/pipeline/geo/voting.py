"""Combine country votes with strong and weak place-name evidence.

The rule is lexicographic, so there are no weights to tune:

1. If any place name produced STRONG evidence, it decides exactly as tributary
   matches did before: multiplied by country votes where they agree, on its
   own where they don't. WEAK evidence only breaks ties among the winners.
2. Otherwise, if there is WEAK evidence:
     - where it agrees with the countries, weak x country decides;
     - where countries were mentioned but none agree, the countries decide
       (a coordinate hit is not trusted to overrule them);
     - where no country voted at all, the weak evidence decides.
3. Otherwise the countries decide, as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Decision:
    winners: tuple[str, ...]
    basis: str
    scores: Mapping[str, Fraction]


def _top(scores: Mapping[str, Fraction]) -> list[str]:
    positive = {b: s for b, s in scores.items() if s > 0}
    if not positive:
        return []
    best = max(positive.values())
    return sorted(b for b, s in positive.items() if s == best)


def _break_ties(winners: list[str], tiebreak: Mapping[str, Fraction]) -> list[str]:
    if len(winners) < 2 or not tiebreak:
        return winners
    support = {b: tiebreak.get(b, 0) for b in winners}
    best = max(support.values())
    if best <= 0:
        return winners
    return sorted(b for b in winners if support[b] == best)


def _agreeing(evidence: Mapping[str, Fraction], countries: Mapping[str, int]) -> dict[str, Fraction]:
    return {b: s * countries[b] for b, s in evidence.items() if s > 0 and countries.get(b, 0) > 0}


def decide(
    country_votes: Mapping[str, int],
    strong: Mapping[str, Fraction],
    weak: Mapping[str, Fraction],
) -> Decision:
    if any(s > 0 for s in strong.values()):
        agreeing = _agreeing(strong, country_votes)
        if agreeing:
            scores, basis = agreeing, "strong evidence x countries"
        else:
            scores, basis = dict(strong), "strong evidence only"
        winners = _break_ties(_top(scores), weak)
    elif any(s > 0 for s in weak.values()):
        agreeing = _agreeing(weak, country_votes)
        if agreeing:
            scores, basis = agreeing, "weak evidence x countries"
        elif any(v > 0 for v in country_votes.values()):
            scores, basis = dict(country_votes), "countries (weak evidence disagreed)"
        else:
            scores, basis = dict(weak), "weak evidence only"
        winners = _top(scores)
    else:
        scores, basis = dict(country_votes), "countries only"
        winners = _top(scores)

    if not winners:
        basis = "no evidence"
    return Decision(tuple(winners), basis, scores)