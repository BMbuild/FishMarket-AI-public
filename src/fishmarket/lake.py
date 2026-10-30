"""Data lake CLI.
  python -m fishmarket.lake inspect <path>            what format is this GBIF download, and are required columns present?
  python -m fishmarket.lake build <path> [--doi DOI] [--allow-noncommercial] [--lake DIR] [--chunksize N]
  python -m fishmarket.lake build --sample            build from the committed synthetic TEST FIXTURE (never real data)
  python -m fishmarket.lake stats [--lake DIR]
"""
import argparse
import json
import sys
from pathlib import Path

from . import crosswalk, gbif, real_data

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "gbif_test_fixture.tsv.gz"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fishmarket.lake")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inspect")
    i.add_argument("path", type=Path)
    b = sub.add_parser("build")
    b.add_argument("path", type=Path, nargs="?")
    b.add_argument("--sample", action="store_true")
    b.add_argument("--doi", default="")
    b.add_argument("--allow-noncommercial", action="store_true")
    b.add_argument("--lake", type=Path, default=None)
    b.add_argument("--chunksize", type=int, default=250_000)
    s = sub.add_parser("stats")
    s.add_argument("--lake", type=Path, default=None)
    a = ap.parse_args(argv)

    if a.cmd == "inspect":
        info = gbif.inspect(a.path)
        print(json.dumps(info, indent=2, default=str))
        return 1 if info["missing_required"] else 0
    if a.cmd == "build":
        src = FIXTURE if a.sample else a.path
        if src is None:
            ap.error("give a path or --sample")
        lake = a.lake or gbif.LAKE
        info = gbif.inspect(src)
        if info["missing_required"]:
            print(info["advice"])
            return 1
        out = gbif.build(src, lake, a.chunksize, a.allow_noncommercial, a.doi, is_test_fixture=a.sample,
                         progress=lambda i, n: print(f"  chunk {i + 1}: {n:,} rows", flush=True))
        gold = gbif.Gold(lake)
        noaa = real_data.load()
        cw = crosswalk.build(noaa.df, gold.taxa)
        (lake / "crosswalk").mkdir(exist_ok=True)
        cw.to_csv(lake / "crosswalk" / "species_crosswalk.csv", index=False)
        crosswalk.review_table(cw).to_csv(lake / "crosswalk" / "species_crosswalk_review.csv", index=False)
        r = out["report"]
        print(f"Rows {r['total_rows']:,}; valid {r['valid_rows']:,} ({r['pass_rate']:.1%}). Taxa {out['manifest']['taxa']:,}.")
        print("NOAA species linked exactly:", int((cw['match_type'] == 'exact').sum()), "of", len(cw), "(see species_crosswalk_review.csv)")
        if a.sample:
            print("NOTE: this is the synthetic TEST FIXTURE, not real GBIF data.")
        return 0
    g = gbif.Gold(a.lake)
    if not g.available:
        print("No lake built yet.")
        return 1
    print(json.dumps({"manifest": g.manifest, "report": g.report}, indent=2))
    for p in sorted((g.lake / "gold").glob("*")):
        print(f"{p.name:<32}{p.stat().st_size / 1e6:>10.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
