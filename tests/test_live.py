"""Live adapters tested with a fake transport. OBIS response shape is ASSUMED from its public docs (total + results);
`python -m fishmarket.live check` verifies the real shapes once you have network access."""
import json
from pathlib import Path

import pytest

from fishmarket import live, real_data
from fishmarket.qa import answer
from fishmarket.qa.context import Context

KEY = "k" * 40


def census_fake(calls):
    def fetch(url):
        calls.append(url)
        flow = "imports" if "/imports/" in url else "exports"
        v = "GEN_VAL_YR" if flow == "imports" else "ALL_VAL_YR"
        c = "I_COMMODITY" if flow == "imports" else "E_COMMODITY"
        return json.dumps([[c, "CTY_CODE", "CTY_NAME", v, "YEAR", "MONTH", "COMM_LVL"],
                           ["0306", "5700", "CHINA", "300000000", "2024", "12", "HS4"],
                           ["0306", "1220", "CANADA", "900000000", "2024", "12", "HS4"],
                           ["0306", "0026", "APEC", "1100000000", "2024", "12", "HS4"],            # group rows, as in the real Census data
                           ["0306", "5XXX", "ASIA", "300000000", "2024", "12", "HS4"],
                           ["0306", "0020", "USMCA (NAFTA)", "900000000", "2024", "12", "HS4"],
                           ["0306", "-", "TOTAL FOR ALL COUNTRIES", "1200000000", "2024", "12", "HS4"]])
    return fetch


def obis_fake(url):
    if "size=1&" in url or url.endswith("size=1"):
        return json.dumps({"total": 123 if "startdate" in url else 99999, "results": [{}]})
    return json.dumps({"total": 99999, "results": [{"decimalLatitude": 40 + i / 100, "decimalLongitude": -70, "month": 1 + i % 12} for i in range(40)]})


def test_census_parsing_and_key_hygiene(tmp_path):
    calls = []
    r = live.trade_by_country("imports", "0306", 2024, key=KEY, fetch=census_fake(calls), cache_dir=tmp_path)
    assert r["total_usd"] == 1_200_000_000 and r["top"][0][0] == "Canada" and r["n_partners"] == 2     # Census total used; group rows (APEC, ASIA, NAFTA) not counted as countries
    assert [n for n, _ in r["top"]] == ["Canada", "China"]
    assert "YEAR=2024" in calls[0] and "COMM_LVL=HS4" in calls[0] and "I_COMMODITY=0306" in calls[0]
    assert all(KEY not in p.read_text() for p in tmp_path.iterdir())                                 # key never cached
    live.trade_by_country("imports", "0306", 2024, key="z" * 40, fetch=census_fake(calls), cache_dir=tmp_path)
    assert len(calls) == 1                                                                           # second call served from cache, key not part of the cache key


def test_census_needs_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    with pytest.raises(live.LiveError, match="key"):
        live.trade_by_country("imports", "0306", 2024, fetch=census_fake([]), cache_dir=tmp_path)


def test_bad_shapes_fail_loudly(tmp_path):
    with pytest.raises(live.LiveError):
        live.trade_by_country("imports", "0306", 2024, key=KEY, fetch=lambda u: "[]", cache_dir=tmp_path / "a")
    with pytest.raises(live.LiveError):
        live.trade_by_country("imports", "0306", 2024, key=KEY, fetch=lambda u: "not json", cache_dir=tmp_path / "b")
    with pytest.raises(live.LiveError):
        live.obis_count("x", fetch=lambda u: json.dumps({"oops": 1}), cache_dir=tmp_path / "c")
    with pytest.raises(live.LiveError):
        live.trade_by_country("imports", "9999", 2024, key=KEY)


def test_obis_profile(tmp_path):
    p = live.obis_profile("Homarus americanus", 2024, fetch=obis_fake, cache_dir=tmp_path)
    assert p["total"] == 99999 and len(p["by_decade"]) == 6 and p["sample_points"] == 40 and len(p["months"]) == 12


pytestmark_noaa = pytest.mark.skipif(not real_data.DEFAULT_CSV.exists(), reason="NOAA csv missing")


@pytestmark_noaa
def test_trade_answer_uses_live_numbers_and_cites(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path)
    monkeypatch.setenv("CENSUS_API_KEY", KEY)
    ctx = Context.load(Path("/nonexistent-lake"), live=True, live_fetch=census_fake([]))
    a = answer.ask("How much American lobster does the US import?", ctx)
    assert a["entry_id"] == "seafood_trade" and "$1.20 billion" in a["answer_md"] and "Canada" in a["answer_md"]
    assert a["origins"] == ["REAL (other public source)"] and a["confidence"] == "Medium"
    assert any("census.gov" in c.lower() for c in a["citations"])
    assert KEY not in json.dumps({k: v for k, v in a.items() if k not in ("plan", "tool_result")}, default=str)


@pytestmark_noaa
def test_trade_falls_back_in_order(tmp_path):
    off = Context.load(Path("/nonexistent-lake"), live=False)
    gen = answer.ask("How much seafood is imported into the US?", off)
    assert gen["origins"] == ["REAL (other public source)"]                       # sourced wiki note beats an invented number
    sp = answer.ask("How much American lobster does the US import?", off)
    assert sp["origins"] == ["SYNTHETIC"] and sp["confidence"] == "Low"          # labelled illustration
    ro = answer.ask("How much American lobster does the US import?", off, real_only=True)
    assert ro["verdict"] == "cannot"


@pytestmark_noaa
def test_live_failure_is_refused_not_guessed(tmp_path):
    def boom(url):
        raise live.LiveError("could not reach test (OSError)")
    ctx = Context.load(Path("/nonexistent-lake"), live=True, live_fetch=boom)
    a = answer.ask("How many OBIS records does Atlantic cod have?", ctx)
    assert a["verdict"] == "cannot" and "Nothing was guessed" in a["answer_md"]


@pytestmark_noaa
def test_obis_off_and_on(monkeypatch, tmp_path):
    monkeypatch.setattr(live, "CACHE_DIR", tmp_path)
    off = Context.load(Path("/nonexistent-lake"), live=False)
    assert "switched off" in answer.ask("How many OBIS records does Atlantic cod have?", off)["answer_md"]
    on = Context.load(Path("/nonexistent-lake"), live=True, live_fetch=obis_fake)
    a = answer.ask("How many OBIS records does Atlantic cod have?", on)
    assert a["verdict"] == "answered" and "99,999" in a["answer_md"]


@pytestmark_noaa
def test_costs_are_fictional_and_never_mixed(tmp_path):
    ctx = Context.load(Path("/nonexistent-lake"), live=False)
    a = answer.ask("What is my profit margin on American lobster?", ctx)
    assert a["origins"] == ["SYNTHETIC"] and a["confidence"] == "Low"
    assert answer.ask("What is my profit margin on American lobster?", ctx, real_only=True)["verdict"] == "cannot"
    assert answer.ask("What is my profit margin on American lobster?", ctx)["answer_md"] == a["answer_md"]    # seeded, repeatable


@pytest.mark.real_dotenv
@pytest.mark.parametrize("raw", [b'\xef\xbb\xbfANTHROPIC_API_KEY="abc"\r\nX=1\r\n', 'ANTHROPIC_API_KEY=abc\r\n'.encode("utf-16"), b"ANTHROPIC_API_KEY='abc'\n"])
def test_dotenv_readers_handle_windows_encodings(tmp_path, monkeypatch, raw):
    from fishmarket import llm
    env = tmp_path / ".env"
    env.write_bytes(raw)
    monkeypatch.setattr(live, "ROOT", tmp_path)
    assert live._dotenv("ANTHROPIC_API_KEY") == "abc"
    real = Path
    monkeypatch.setattr(llm, "Path", lambda *a: real(tmp_path / "src" / "fishmarket" / "llm.py") if a and str(a[0]).endswith("llm.py") else real(*a))
    assert llm._dotenv_value("ANTHROPIC_API_KEY") == "abc"
