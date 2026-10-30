import json
from pathlib import Path

import pandas as pd
import pytest

from fishmarket import crosswalk, gbif, real_data

FIX = Path(__file__).parent / "fixtures" / "gbif_test_fixture.tsv.gz"


@pytest.fixture(scope="module")
def lake(tmp_path_factory):
    p = tmp_path_factory.mktemp("lake")
    gbif.build(FIX, p, chunksize=9000, is_test_fixture=True, built_at="test")
    return gbif.Gold(p)


def test_inspect_reports_format_and_missing_columns(tmp_path):
    info = gbif.inspect(FIX)
    assert info["format"] == "simple_csv" and info["missing_required"] == []
    bad = tmp_path / "x.tsv"
    bad.write_text("gbifID\tspecies\n1\tfoo\n")
    out = gbif.inspect(bad)
    assert "taxonKey" in out["missing_required"] and "Re-request" in out["advice"]


def test_gate_counts_match_the_planted_problems(lake):
    r = lake.report["reason_counts"]
    assert r["zero_coordinates"] == 72 and r["missing_coordinates"] == 60 and r["absence_record"] == 60
    assert r["fossil_or_living_specimen"] == 48 and r["bad_year"] == 36 and r["gbif_coordinate_issue"] == 48
    assert r["exact_duplicate"] == 84 and r["coordinates_out_of_range"] == 48
    assert r["license_non_commercial"] == 60 and r["coordinate_uncertainty_over_10km"] == 60
    assert sum(lake.report["by_status"].values()) == lake.report["total_rows"] == 39096


def test_chunk_size_does_not_change_the_result(lake, tmp_path):
    gbif.build(FIX, tmp_path, chunksize=39096, is_test_fixture=True, built_at="t")
    a, b = lake.cells.sort_values(["taxon", "cell_lat", "cell_lon", "year_i"]).reset_index(drop=True), \
        gbif.Gold(tmp_path).cells.sort_values(["taxon", "cell_lat", "cell_lon", "year_i"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_noncommercial_flag_changes_review_to_valid(tmp_path):
    r = gbif.build(FIX, tmp_path, allow_noncommercial=True, is_test_fixture=True)["report"]
    assert "license_non_commercial" not in r["reason_counts"]


def test_manifest_marks_fixture_and_regions_are_assigned(lake):
    assert lake.manifest["is_test_fixture"] is True and "approximate" in lake.manifest["region_method"]
    reg = lake.year[lake.year["taxon"] == 9000004]["region"].unique()
    assert list(reg) == ["Alaska"]


def test_aggregates_consistent_with_valid_rows(lake):
    assert lake.cells["n"].sum() == lake.report["valid_rows"]
    assert lake.year["n"].sum() == lake.taxa["n_valid"].sum() == lake.cells["n"].sum()
    assert lake.points.groupby("taxon").size().max() <= gbif.POINTS_PER_TAXON


def test_assign_regions_boxes():
    lat, lon = pd.Series([42.5, 29.0, 58.0, 20.5, 0.0]), pd.Series([-68.0, -90.0, -150.0, -157.0, 0.0])
    got = list(gbif.assign_regions(lat, lon))
    assert got[:4] == ["New England", "Gulf", "Alaska", "Hawaii"] and pd.isna(got[4])


# ---------------- crosswalk
@pytest.fixture(scope="module")
def cw(lake):
    if not real_data.DEFAULT_CSV.exists():
        pytest.skip("NOAA csv missing")
    return crosswalk.build(real_data.load().df, lake.taxa)


@pytest.mark.parametrize("noaa,expected", [("American lobster", 9000001), ("Atlantic cod", 9000002), ("Bluefin tuna", 9000003),
                                           ("Walleye pollock", 9000004), ("Pacific cod", 9000005), ("Sockeye salmon", 9000006),
                                           ("Blue crab", 9000007), ("Brown shrimp", 9000008), ("Sea scallop", 9000009),
                                           ("Atlantic menhaden", 9000011), ("Summer flounder", 9000012)])
def test_exact_matches(cw, noaa, expected):
    r = cw[cw["noaa_species"] == noaa].iloc[0]
    assert r["match_type"] == "exact" and r["gbif_taxon_keys"] == str(expected)


def test_synonym_override_is_labelled(cw):
    r = cw[cw["noaa_species"] == "Dungeness crab"].iloc[0]
    assert r["match_type"] == "override" and r["gbif_taxon_keys"] == "9000010" and r["confidence"] < 1


def test_genus_family_and_unmatched_cases_are_not_guessed(cw):
    assert cw[cw["noaa_species"] == "Menhadens"].iloc[0]["match_type"] == "genus_level"      # genus 'Brevoortia ' -> tyrannus only
    assert cw[cw["noaa_species"] == "Herrings"].iloc[0]["match_type"] == "group"            # family Clupeidae
    assert cw[cw["noaa_species"] == "River herrings"].iloc[0]["match_type"] == "group"      # Alosa spp.
    assert cw[cw["noaa_species"] == "Haddock"].iloc[0]["match_type"] == "none"              # valid name, not in this GBIF data
    assert cw[cw["noaa_species"] == "Walleye pollock"].iloc[0]["confidence"] == 1.0


def test_review_table_lists_every_non_exact(cw):
    rv = crosswalk.review_table(cw)
    assert (rv["match_type"] != "exact").all() and len(rv) == (cw["match_type"] != "exact").sum()
    assert crosswalk.taxon_keys(cw, "American lobster") == ([9000001], "exact")
    assert crosswalk.taxon_keys(cw, "Herrings") == ([], "group")


def test_folder_of_per_species_api_exports(tmp_path):
    """The format written by scripts/download_external_datasets.py: one CSV per species, API column names."""
    d = tmp_path / "external_data"
    d.mkdir()
    head = "key,taxonKey,speciesKey,species,scientificName,family,decimalLatitude,decimalLongitude,year,month,basisOfRecord,occurrenceStatus,issues,license,datasetKey,coordinateUncertaintyInMeters\n"
    rows = "".join(f"{i},5,5,Gadus morhua,Gadus morhua L.,Gadidae,{42 + i / 100:.3f},{-69 - i / 100:.3f},{1990 + i % 30},{1 + i % 12},HUMAN_OBSERVATION,PRESENT,\"['COORDINATE_ROUNDED']\" if False else \"[]\",http://creativecommons.org/licenses/by-nc/4.0/legalcode,ds{i % 3},50\n" for i in range(40))
    (d / "gbif_Gadus_morhua.csv").write_text(head + rows.replace("\"['COORDINATE_ROUNDED']\" if False else \"[]\"", "\"[]\""))
    (d / "gbif_Broken.csv").write_text("not,a,gbif,file\n1,2,3,4\n")
    info = gbif.detect_format(d)
    assert info["format"] == "api_csv_dir" and len(info["files"]) == 2
    out = gbif.build(d, tmp_path / "lake", allow_noncommercial=True, built_at="2026-01-01T00:00:00")
    m = out["manifest"]
    assert m["source_kind"] == "api_sample" and m["skipped_files"] == ["gbif_Broken.csv"]
    assert out["report"]["total_rows"] == 40 and out["report"]["valid_rows"] > 0
    g = gbif.Gold(tmp_path / "lake")
    assert g.available and len(g.taxa) == 1
