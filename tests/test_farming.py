"""OECD aquaculture and FishWatch adapters with a fake transport. The response shapes follow OECD's SDMX structure/CSV formats
and the FishWatch field names documented by its connector; `python -m fishmarket.live check` confirms them for real."""
import json
from pathlib import Path

import pytest

from fishmarket import live, real_data
from fishmarket.qa import answer, router
from fishmarket.qa.context import Context

STRUCT = """<?xml version="1.0"?><m:Structure xmlns:m="urn:msg" xmlns:s="urn:str"><m:Structures>
<s:Dataflows><s:Dataflow id="DSD_FISH_PROD@DF_FISH_AQUA" agencyID="OECD.TAD.ATM" version="1.0"/></s:Dataflows>
<s:DataStructures><s:DataStructure id="DSD_FISH_PROD"><s:DataStructureComponents><s:DimensionList>
<s:Dimension id="REF_AREA" position="1"/><s:Dimension id="MEASURE" position="2"/><s:Dimension id="SPECIES" position="3"/><s:Dimension id="UNIT_MEASURE" position="4"/>
<s:TimeDimension id="TIME_PERIOD" position="5"/></s:DimensionList></s:DataStructureComponents></s:DataStructure></s:DataStructures></m:Structures></m:Structure>"""
HEAD = "STRUCTURE,STRUCTURE_ID,ACTION,REF_AREA,Reference area,MEASURE,Measure,SPECIES,Species,UNIT_MEASURE,Unit of measure,TIME_PERIOD,Time period,OBS_VALUE,Observation value,UNIT_MULT,Unit multiplier"


def row(area, aname, code, label, year, v):
    return f'DATAFLOW,X,I,{area},{aname},AQUA,Aquaculture production,{code},"{label}",T,Tonnes,{year},{year},{v},,0,Units'


def oecd_fake(calls):
    def fetch(url):
        calls.append(url)
        if "/dataflow/" in url:
            return STRUCT
        if "/USA..." in url or "/USA.." in url:
            return "\n".join([HEAD, row("USA", "United States", "SAL", "Atlantic salmon [Salmo salar]", 2005, 10000), row("USA", "United States", "SAL", "Atlantic salmon [Salmo salar]", 2022, 15000),
                              row("USA", "United States", "OYG", "Pacific cupped oyster [Crassostrea gigas]", 2022, 9000)])
        if "..SAL." in url:
            return "\n".join([HEAD, row("NOR", "Norway", "SAL", "Atlantic salmon [Salmo salar]", 2022, 1500000), row("CHL", "Chile", "SAL", "Atlantic salmon [Salmo salar]", 2022, 700000),
                              row("USA", "United States", "SAL", "Atlantic salmon [Salmo salar]", 2022, 15000)])
        raise live.LiveError("unexpected test url " + url)
    return fetch


FW = [{"Species Name": "Atlantic Salmon (Farmed)", "Scientific Name": "<em>Salmo salar</em>", "Harvest Type": "Farmed", "Path": "/profiles/atlantic-salmon-farmed",
       "Farming Methods": "<p>Salmon are raised in net pens in the ocean.</p>", "Feeds": "<p>Farmed salmon eat feed made of fishmeal &amp; plant proteins.</p>",
       "Production": "<p>Most U.S. farmed salmon comes from Maine and Washington.</p>", "last_update": "05/11/2019"},
      {"Species Name": "Atlantic Cod", "Scientific Name": "Gadus morhua", "Harvest Type": "Wild", "Path": "/profiles/atlantic-cod"}]


def test_oecd_dimension_order_and_parsing(tmp_path):
    calls = []
    a = live.aquaculture("Salmo salar", "USA", fetch=oecd_fake(calls), cache_dir=tmp_path)
    assert any("/data/OECD.TAD.ATM,DSD_FISH_PROD@DF_FISH_AQUA,/USA..." in c for c in calls)          # key built from the structure, agency looked up
    assert a["match"] == "species" and a["series"]["T"] == {2005: 10000.0, 2022: 15000.0}
    assert a["top_countries"][0] == ("Norway", 1500000.0) and a["rank"] == 3 and a["n_countries"] == 3


def test_oecd_bad_shapes_fail_loudly(tmp_path):
    with pytest.raises(live.LiveError):
        live.oecd_structure(fetch=lambda u: "not xml", cache_dir=tmp_path / "a")
    with pytest.raises(live.LiveError):
        live.aquaculture("Salmo salar", "USA", fetch=lambda u: STRUCT if "/dataflow/" in u else "<error/>", cache_dir=tmp_path / "b")


def test_fishwatch_prefers_the_farmed_profile_and_strips_html(tmp_path):
    rec = live.fishwatch_farmed("Atlantic salmon", "Salmo salar", fetch=lambda u: json.dumps(FW), cache_dir=tmp_path)
    assert rec["name"] == "Atlantic Salmon (Farmed)" and rec["Feeds"] == "Farmed salmon eat feed made of fishmeal & plant proteins."
    assert live.fishwatch_farmed("Unicorn fish", "", fetch=lambda u: json.dumps(FW), cache_dir=tmp_path) is None
    with pytest.raises(live.LiveError):
        live.fishwatch_list(fetch=lambda u: json.dumps({"retired": True}), cache_dir=tmp_path / "c")


pytestmark_noaa = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


@pytestmark_noaa
def test_farm_questions_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path)
    fake_o = oecd_fake([])

    def fetch(url):
        return json.dumps(FW) if "fishwatch" in url else fake_o(url)
    ctx = Context.load(Path("/nonexistent-lake"), live=True, live_fetch=fetch)
    a = answer.ask("How much Atlantic salmon does the US farm?", ctx)
    assert a["entry_id"] == "aquaculture_production" and "15,000 tonnes in 2022" in a["answer_md"] and "+50%" in a["answer_md"]
    assert "Norway 1,500,000" in a["answer_md"] and a["confidence"] == "Medium"
    b = answer.ask("What do farmed salmon eat?", ctx)
    assert b["entry_id"] == "farming_profile" and "fishmeal & plant proteins" in b["answer_md"] and "Atlantic salmon" in b["answer_md"]
    assert any("fishwatch" in c.lower() for c in b["citations"])


@pytestmark_noaa
def test_farm_questions_off_and_general(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "LOCAL_OECD", tmp_path / "none.csv")
    monkeypatch.setattr(live, "LOCAL_OECD_CLEAN", tmp_path / "none_clean.csv")
    monkeypatch.setattr(live, "LOCAL_FISHWATCH", tmp_path / "none.json")
    off = Context.load(Path("/nonexistent-lake"), live=False)
    assert "isn't downloaded yet" in answer.ask("How much Atlantic salmon does the US farm?", off)["answer_md"]
    g = answer.ask("How much of the US seafood supply is farmed?", off)
    assert g["entry_id"] == "wiki_lookup" and "7 percent" in g["answer_md"]
    assert router.plan("What do farmed salmon eat?", off).species == ["Atlantic salmon"]


@pytestmark_noaa
def test_local_snapshot_files_are_used_without_network(monkeypatch, tmp_path):
    csvf, fw = tmp_path / "aqua.csv", tmp_path / "fw.json"
    csvf.write_text("\n".join([HEAD, row("USA", "United States", "SAL", "Atlantic salmon [Salmo salar]", 2010, 8000), row("USA", "United States", "SAL", "Atlantic salmon [Salmo salar]", 2022, 16000),
                                row("NOR", "Norway", "SAL", "Atlantic salmon [Salmo salar]", 2022, 1500000)]), encoding="utf-8")
    fw.write_text(json.dumps(FW), encoding="utf-8")
    monkeypatch.setattr(live, "LOCAL_OECD", csvf)
    monkeypatch.setattr(live, "LOCAL_OECD_CLEAN", tmp_path / "no_clean.csv")
    monkeypatch.setattr(live, "LOCAL_FISHWATCH", fw)

    def no_network(url):
        raise AssertionError("network used: " + url)
    monkeypatch.setattr(live, "_default_fetch", no_network)
    ctx = Context.load(Path("/nonexistent-lake"), live=False)
    a = answer.ask("How much Atlantic salmon does the US farm?", ctx)
    assert a["verdict"] == "answered" and "16,000 tonnes in 2022" in a["answer_md"] and "+100%" in a["answer_md"] and "ranks 2 of 2" in a["answer_md"]
    b = answer.ask("How is Atlantic salmon farmed?", ctx)
    assert b["verdict"] == "answered" and "net pens" in b["answer_md"]
