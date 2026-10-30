import pytest

from fishmarket import species_info as si


def fake_get(url, params=None, timeout=12):
    if url.endswith("/species/match"):
        return {"usageKey": 2227, "matchType": "EXACT", "confidence": 98, "rank": "SPECIES", "status": "ACCEPTED",
                "scientificName": "Homarus americanus", "family": "Nephropidae", "order": "Decapoda"}
    if url.endswith("/vernacularNames"):
        return {"results": [{"vernacularName": "American lobster", "language": "eng"}, {"vernacularName": "Homard", "language": "fra"},
                            {"vernacularName": "American lobster", "language": "eng"}]}
    if url.endswith("/occurrence/search"):
        assert params["country"] == "US" and params["limit"] <= 300
        return {"count": 1234, "results": [{"decimalLatitude": 43.1, "decimalLongitude": -70.2}, {"decimalLatitude": None}]}
    if url.endswith("/species"):
        return {"count": 0, "returned": 0, "data": [], "error": None}
    raise AssertionError(url)


def test_lookup_combines_gbif_and_handles_fishbase_miss(tmp_path):
    r = si.lookup("homarus americanus", fake_get, tmp_path / "c.json")
    assert r["gbif"]["trusted"] and r["gbif"]["common_names"] == ["American lobster"]
    assert r["gbif"]["points"] == [(43.1, -70.2)] and r["gbif"]["occurrence_count_us"] == 1234
    assert r["fishbase"]["found"] is False and "SeaLifeBase" in r["fishbase"]["note"]
    assert r["errors"] == [] and r["from_cache"] is False
    assert si.lookup("Homarus americanus", lambda *a, **k: 1 / 0, tmp_path / "c.json")["from_cache"] is True


def test_low_confidence_match_is_not_trusted():
    g = si.gbif_lookup("Brevoortia", lambda u, p=None, timeout=12: {"usageKey": 1, "matchType": "HIGHERRANK", "confidence": 60})
    assert g["trusted"] is False and "points" not in g


def test_network_failure_is_reported_not_cached(tmp_path):
    def boom(url, params=None, timeout=12):
        raise si.SpeciesInfoError("URLError: blocked")
    r = si.lookup("Gadus morhua", boom, tmp_path / "c.json")
    assert r["gbif"] is None and r["errors"] and not (tmp_path / "c.json").exists()


def test_fishbase_hit_and_base_fallback():
    calls = []

    def get(url, params=None, timeout=12):
        calls.append(url)
        if "/fishbase/" in url:
            return {"count": 1, "returned": 1, "error": None, "data": [{"SpecCode": 69, "FBname": "Atlantic cod", "Length": 200, "junk": 1}]}
        raise si.SpeciesInfoError("down")
    r = si.fishbase_lookup("Gadus morhua", get, ["https://x.org", "https://x.org/fishbase"])
    assert r["found"] and r["facts"] == {"SpecCode": 69, "FBname": "Atlantic cod", "Length": 200} and len(calls) == 2
    assert si.fishbase_lookup("Brevoortia", get)["found"] is False
