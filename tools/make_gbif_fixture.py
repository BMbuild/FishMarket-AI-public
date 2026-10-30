"""Builds the GBIF-shaped TEST FIXTURE used by the offline tests. SYNTHETIC: ids, coordinates and dates are generated.
It exists so the lake, gate, crosswalk and QA code can be tested without the multi-GB real download. It must never be shown to a
user as real GBIF data (the lake manifest carries is_test_fixture=true and the app says so).
Usage: python tools/make_gbif_fixture.py  -> tests/fixtures/gbif_test_fixture.tsv.gz"""
import gzip
import sys
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "gbif_test_fixture.tsv.gz"
SEED = 20261027

# name, taxonKey (fake), family, scientificName as GBIF would list, boxes [(lat0,lat1,lon0,lon1,weight)], months weights (12), lat drift per year
SPECIES = [
    ("Homarus americanus", 9000001, "Nephropidae", "Homarus americanus (H. Milne Edwards, 1837)", [(41.5, 45.5, -71, -66, 1)], [0, 0, 0, 0, 1, 2, 3, 3, 3, 2, 1, 0], 0.03),
    ("Gadus morhua", 9000002, "Gadidae", "Gadus morhua Linnaeus, 1758", [(41.0, 43.5, -70.5, -66, 1)], [1] * 12, 0.05),
    ("Thunnus thynnus", 9000003, "Scombridae", "Thunnus thynnus (Linnaeus, 1758)", [(38.5, 43.0, -73, -67, 1)], [0, 0, 0, 0, 0, 1, 4, 5, 5, 3, 0, 0], 0.0),
    ("Gadus chalcogrammus", 9000004, "Gadidae", "Gadus chalcogrammus Pallas, 1814", [(52, 60, -170, -150, 1)], [2, 3, 3, 2, 1, 1, 2, 3, 3, 2, 1, 1], 0.0),
    ("Gadus macrocephalus", 9000005, "Gadidae", "Gadus macrocephalus Tilesius, 1810", [(52, 59, -170, -150, 3), (44, 48.5, -126, -123, 1)], [1] * 12, 0.0),
    ("Oncorhynchus nerka", 9000006, "Salmonidae", "Oncorhynchus nerka (Walbaum, 1792)", [(55, 61, -165, -148, 1)], [0, 0, 0, 0, 1, 4, 6, 4, 1, 0, 0, 0], 0.0),
    ("Callinectes sapidus", 9000007, "Portunidae", "Callinectes sapidus Rathbun, 1896", [(27.5, 30.2, -94, -85, 3), (32, 35, -80, -76, 2), (37, 39.5, -77, -75.5, 2)], [0, 0, 0, 2, 4, 5, 5, 5, 4, 3, 1, 0], 0.0),
    ("Penaeus aztecus", 9000008, "Penaeidae", "Penaeus aztecus Ives, 1891", [(27.5, 30.2, -97, -86, 1)], [0, 0, 0, 1, 3, 5, 5, 4, 3, 2, 0, 0], 0.0),
    ("Placopecten magellanicus", 9000009, "Pectinidae", "Placopecten magellanicus (Gmelin, 1791)", [(40.5, 44.5, -71, -66, 2), (37.5, 40.5, -74, -70, 1)], [1] * 12, 0.0),
    ("Metacarcinus magister", 9000010, "Cancridae", "Metacarcinus magister (Dana, 1852)", [(37, 48.5, -125.5, -122.5, 1)], [1, 1, 1, 1, 2, 3, 3, 3, 2, 1, 1, 1], 0.0),
    ("Brevoortia tyrannus", 9000011, "Clupeidae", "Brevoortia tyrannus (Latrobe, 1802)", [(35.5, 41, -76.5, -70, 2), (30, 35, -80.5, -76, 1)], [0, 0, 1, 2, 3, 4, 4, 4, 3, 2, 1, 0], 0.0),
    ("Paralichthys dentatus", 9000012, "Paralichthyidae", "Paralichthys dentatus (Linnaeus, 1766)", [(36, 41.5, -76, -69.5, 1)], [0, 0, 1, 2, 3, 4, 4, 4, 3, 2, 1, 0], 0.0),
]
N_PER = 3200
YEARS = np.arange(1990, 2025)
DATASETS = ["fixture-ds-a", "fixture-ds-b", "fixture-ds-c"]


def good_rows(rng, name, key, fam, sci, boxes, mweights, drift):
    n = N_PER
    yw = np.linspace(0.4, 1.6, len(YEARS))                    # more records later: sampling effort grows
    years = rng.choice(YEARS, n, p=yw / yw.sum())
    months = rng.choice(np.arange(1, 13), n, p=np.array(mweights) / sum(mweights))
    w = np.array([b[4] for b in boxes], float)
    bi = rng.choice(len(boxes), n, p=w / w.sum())
    lat = np.empty(n)
    lon = np.empty(n)
    for i, b in enumerate(boxes):
        m = bi == i
        lat[m] = rng.uniform(b[0], b[1], m.sum())
        lon[m] = rng.uniform(b[2], b[3], m.sum())
    lat = lat + drift * (years - 1990) + rng.normal(0, 0.15, n)     # optional northward drift
    lat, lon = np.round(lat + 0.0013, 4), np.round(lon + 0.0017, 4)   # avoid accidental whole degrees
    days = rng.integers(1, 28, n)
    return pd.DataFrame({
        "taxonKey": key, "speciesKey": key, "scientificName": sci, "species": name, "genus": name.split()[0], "family": fam,
        "decimalLatitude": lat, "decimalLongitude": lon, "coordinateUncertaintyInMeters": rng.choice([10, 100, 1000, 5000], n),
        "eventDate": [f"{y}-{m:02d}-{d:02d}" for y, m, d in zip(years, months, days)], "year": years, "month": months,
        "basisOfRecord": rng.choice(["HUMAN_OBSERVATION", "MACHINE_OBSERVATION", "PRESERVED_SPECIMEN"], n, p=[0.7, 0.1, 0.2]),
        "occurrenceStatus": "PRESENT", "individualCount": rng.integers(1, 5, n).astype(str), "countryCode": "US", "stateProvince": "",
        "issue": "", "datasetKey": rng.choice(DATASETS, n), "license": rng.choice(["CC0_1_0", "CC_BY_4_0"], n), "establishmentMeans": ""})


def planted(rng, base):
    """Copies of good rows, each damaged in one known way. Counts are fixed so tests can assert them."""
    out = []

    def dmg(k, jitter=False, **kw):
        d = base.sample(k, random_state=int(rng.integers(1_000_000))).copy()
        for c, v in kw.items():
            d[c] = v
        if jitter:                                   # so the damaged copy is not an exact duplicate of its source row
            d["decimalLatitude"] = d["decimalLatitude"].astype(float) + 0.0007
        out.append(d)
    dmg(6, decimalLatitude=0.0, decimalLongitude=0.0)                                    # zero_coordinates
    dmg(5, decimalLatitude="", decimalLongitude="")                                      # missing_coordinates
    dmg(4, decimalLatitude=95.0)                                                         # out of range
    dmg(5, occurrenceStatus="ABSENT")
    dmg(4, basisOfRecord="FOSSIL_SPECIMEN")
    dmg(3, year=1500)                                                                    # bad_year
    dmg(4, issue="PRESUMED_SWAPPED_COORDINATE")
    dmg(5, jitter=True, coordinateUncertaintyInMeters=50000)                                          # review
    dmg(4, decimalLatitude=42.0, decimalLongitude=-68.0)                                 # review: whole degrees
    dmg(5, jitter=True, license="CC_BY_NC_4_0")                                                       # review (default build)
    dmg(3, basisOfRecord="PRESERVED_SPECIMEN", year=1850, eventDate="1850-06-01")        # review old specimen
    dmg(3, jitter=True, establishmentMeans="INTRODUCED")                                              # review
    return pd.concat(out, ignore_index=True)


def main():
    rng = np.random.default_rng(SEED)
    frames = []
    for name, key, fam, sci, boxes, mw, drift in SPECIES:
        g = good_rows(rng, name, key, fam, sci, boxes, mw, drift)
        # exact duplicates: the 7 rows below are copies of rows already present
        dups = g.iloc[:7].copy()
        frames += [g, planted(rng, g), dups]
    df = pd.concat(frames, ignore_index=True).sample(frac=1, random_state=1).reset_index(drop=True)
    df.insert(0, "gbifID", np.arange(7_000_000_001, 7_000_000_001 + len(df)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        df.to_csv(f, sep="\t", index=False)
    print(len(df), "rows ->", OUT)


if __name__ == "__main__":
    sys.exit(main())
