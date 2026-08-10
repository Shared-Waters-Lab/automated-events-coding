"""Step 6 - Event Deduplication (rule-based, not LLM).

Looks up similar previously-collected events/facts and checks for duplicates
before accepting a new record.

Matching tiers (exact-key, per current plan -- may need a fuzzy/similarity
fallback once real data quality is known; see spec's open questions):
  6.1 Primary keys: date, entity_list, bcode
  6.2 Secondary keys: dyad_pairs, issue_area, bar_scale

Outcome: duplicate found / ambiguous -> flag for human review; no match -> new.
"""

from __future__ import annotations

from automated_events_coding.pipeline.schemas import DedupOutcome, DedupResult, EventRecord


def _primary_key(record: EventRecord) -> tuple:
    return (
        record.date.day,
        record.date.month,
        record.date.year,
        tuple(record.entity_list),
        record.bcode,
    )


def _secondary_key(record: EventRecord) -> tuple:
    return (tuple(record.dyad_pairs), record.issue_area, record.bar_scale)


def check_duplicate(candidate: EventRecord, existing_records: list[EventRecord]) -> DedupResult:
    primary_matches = [r for r in existing_records if _primary_key(r) == _primary_key(candidate)]

    if not primary_matches:
        return DedupResult(outcome=DedupOutcome.NEW)

    if len(primary_matches) == 1:
        return DedupResult(outcome=DedupOutcome.DUPLICATE, matched=primary_matches[0])

    secondary_matches = [r for r in primary_matches if _secondary_key(r) == _secondary_key(candidate)]
    if len(secondary_matches) == 1:
        return DedupResult(outcome=DedupOutcome.DUPLICATE, matched=secondary_matches[0])

    return DedupResult(outcome=DedupOutcome.AMBIGUOUS)
