"""Tier 1: the tributary dictionary (spreadsheet entries + imported aliases).

Lookups are exact matches on normalize.key_tiers. Within a tier the curated
spreadsheet list is checked before the imported alias table, so an alias can
never override a curated name that matches equally well.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from .normalize import key_tiers, lookup_keys, norm


class AliasRow(NamedTuple):
    bcode: str
    canonical: str  # the spreadsheet name this alias belongs to
    qid: str  # Wikidata item for that name ("" if none)
    alias: str


@dataclass(frozen=True)
class DictEntry:
    bcode: str
    canonical: str
    qid: str | None = None

    @property
    def entity(self) -> str:
        return f"wd:{self.qid}" if self.qid else f"trib:{self.bcode}:{norm(self.canonical)}"


def load_alias_table(path: str | Path) -> list[AliasRow]:
    """Read the CSV written by `build_assets aliases`."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = {"bcode", "canonical", "qid", "alias"} - set(df.columns)
    if missing:
        raise ValueError(f"{path}: alias table is missing columns {sorted(missing)}")
    return [
        AliasRow(r.bcode, r.canonical, r.qid, r.alias)
        for r in df.itertuples(index=False)
        if r.bcode and r.canonical
    ]


class TributaryDictionary:
    def __init__(self, entries: Iterable[tuple[str, str]], aliases: Iterable[AliasRow] = ()):
        """entries: (bcode, name) pairs from the basin spreadsheet."""
        aliases = list(aliases)
        qid_for = {(a.bcode, norm(a.canonical)): a.qid for a in aliases if a.qid}

        self._primary: dict[str, set[DictEntry]] = defaultdict(set)
        self._alias: dict[str, set[DictEntry]] = defaultdict(set)
        known: dict[str, set[str]] = defaultdict(set)

        for bcode, name in entries:
            entry = DictEntry(bcode, name, qid_for.get((bcode, norm(name))))
            for key in lookup_keys(name):
                self._primary[key].add(entry)
            if entry.qid:
                known[entry.qid].add(bcode)

        for a in aliases:
            entry = DictEntry(a.bcode, a.canonical, a.qid or None)
            for key in lookup_keys(a.alias):
                self._alias[key].add(entry)
            if a.qid:
                known[a.qid].add(a.bcode)

        self.qid_to_bcodes: dict[str, frozenset[str]] = {q: frozenset(b) for q, b in known.items()}

    def lookup(self, name: str) -> tuple[str, frozenset[DictEntry]] | None:
        """Return (matched keys, entries) for the first key tier that hits."""
        for keys in key_tiers(name, query=True):
            for table in (self._primary, self._alias):
                matched = [k for k in keys if table.get(k)]
                if matched:
                    return " | ".join(matched), frozenset(e for k in matched for e in table[k])
        return None