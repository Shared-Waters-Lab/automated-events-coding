"""Build the cascade's local data. Run once, and again when sources update.

1) Local gazetteer (GeoNames hydrography + GRanD dams + country names):

    python -m automated_events_coding.pipeline.geo.build_assets gazetteer \\
        --geonames allCountries.zip --country-info countryInfo.txt \\
        --grand GRanD_dams_v1_3.shp \\
        --out automated_events_coding/static/geo_gazetteer.sqlite

2) Alias table: resolve each spreadsheet basin/tributary name to a Wikidata
   item, then import that item's labels and aliases in every language:

    python -m automated_events_coding.pipeline.geo.build_assets aliases \\
        --gazetteer automated_events_coding/static/geo_gazetteer.sqlite \\
        --out automated_events_coding/static/tributary_aliases.csv \\
        --review tributary_aliases_review.csv \\
        --overrides tributary_qid_overrides.csv \\
        --user-agent "AEC basin lookup (you@example.org)"

   A name is linked only when exactly one Wikidata item survives the exact
   name, type and riparian-country filters. Everything else goes to the review
   CSV. To settle a review row, add (bcode, canonical, qid) to the overrides
   CSV; leave qid blank to record that the name has no Wikidata item. Then
   rerun -- API responses are cached, so reruns are quick.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from .cache import JsonCache
from .gazetteer import GazetteerWriter, LocalGazetteer, load_country_info, load_geonames, load_grand
from .normalize import classify_route, norm
from .wikidata import HttpTransport, WikidataClient, WikidataError

logger = logging.getLogger(__name__)


def cmd_gazetteer(args: argparse.Namespace) -> None:
    with GazetteerWriter(args.out) as writer:
        if args.country_info:
            logger.info("countryInfo: %d countries", load_country_info(writer, args.country_info))
        logger.info("GeoNames: %d water features", load_geonames(writer, args.geonames))
        if args.grand:
            logger.info("GRanD: %d dams", load_grand(writer, args.grand))
    logger.info("Wrote %s", args.out)


def _load_overrides(path: Path | None) -> dict[tuple[str, str], str]:
    if path is None or not path.exists():
        return {}
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return {(r.bcode, norm(r.canonical)): r.qid.strip() for r in df.itertuples(index=False)}


def cmd_aliases(args: argparse.Namespace) -> None:
    from automated_events_coding.pipeline.step2_location import _build_index

    idx = _build_index()
    gazetteer = LocalGazetteer(args.gazetteer)
    wd = WikidataClient(
        HttpTransport(args.user_agent), JsonCache(args.cache), languages=args.search_languages
    )
    overrides = _load_overrides(args.overrides)

    accepted: list[tuple[str, str, str, str]] = []  # bcode, canonical, qid, how
    review: list[dict] = []
    for i, (bcode, canonical) in enumerate(idx.trib_entries, 1):
        if i % 100 == 0:
            logger.info("%d/%d names", i, len(idx.trib_entries))
        key = (bcode, norm(canonical))
        if key in overrides:
            if overrides[key]:
                accepted.append((bcode, canonical, overrides[key], "override"))
            continue

        riparian = frozenset(
            code for c in idx.basin_countries.get(bcode, ()) for code in gazetteer.country_iso2(c)
        )
        try:
            candidates = wd.find_candidates(canonical, classify_route(canonical), riparian)
        except WikidataError as exc:
            review.append({"bcode": bcode, "canonical": canonical, "reason": f"error: {exc}",
                           "candidates": ""})
            continue
        if len(candidates) == 1:
            accepted.append((bcode, canonical, candidates[0].qid, "wikidata"))
        else:
            review.append({
                "bcode": bcode, "canonical": canonical,
                "reason": "no match" if not candidates else "ambiguous",
                "candidates": "; ".join(f"{c.qid} {c.label} -- {c.description}" for c in candidates),
            })

    names = wd.names({qid for _, _, qid, _ in accepted}, args.alias_languages)
    rows = []
    for bcode, canonical, qid, how in accepted:
        rows.append({"bcode": bcode, "canonical": canonical, "qid": qid, "alias": canonical,
                     "language": "", "source": how})
        seen = {norm(canonical)}
        for language, text in names.get(qid, []):
            if norm(text) and norm(text) not in seen:
                seen.add(norm(text))
                rows.append({"bcode": bcode, "canonical": canonical, "qid": qid, "alias": text,
                             "language": language, "source": "wikidata"})

    pd.DataFrame(rows, columns=["bcode", "canonical", "qid", "alias", "language", "source"]).to_csv(
        args.out, index=False)
    pd.DataFrame(review, columns=["bcode", "canonical", "reason", "candidates"]).to_csv(
        args.review, index=False)
    logger.info("Linked %d of %d names (%d aliases); %d need review -> %s",
                len(accepted), len(idx.trib_entries), len(rows), len(review), args.review)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gazetteer", help="build the local GeoNames/GRanD gazetteer")
    g.add_argument("--geonames", type=Path, required=True)
    g.add_argument("--country-info", type=Path)
    g.add_argument("--grand", type=Path)
    g.add_argument("--out", type=Path, required=True)
    g.set_defaults(func=cmd_gazetteer)

    a = sub.add_parser("aliases", help="link spreadsheet names to Wikidata and import aliases")
    a.add_argument("--gazetteer", type=Path, required=True)
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--review", type=Path, required=True)
    a.add_argument("--overrides", type=Path)
    a.add_argument("--user-agent", required=True, help="name and contact, per Wikimedia policy")
    a.add_argument("--cache", type=Path,
                   default=Path.home() / ".cache" / "automated_events_coding" / "geo_cache.sqlite")
    a.add_argument("--search-languages", nargs="+", default=["en"])
    a.add_argument("--alias-languages", nargs="*", default=None,
                   help="limit imported aliases to these languages (default: all)")
    a.set_defaults(func=cmd_aliases)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()