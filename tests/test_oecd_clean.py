import pandas as pd

from fishmarket import oecd_clean


def frame(rows):
    cols = ["REF_AREA", "Reference area", "MEASURE", "Measure", "SPECIES", "Species", "UNIT_MEASURE", "Unit of measure",
            "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "UNIT_MULT"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows], dtype=str)


def r(area, sp, label, unit, year, v, status="", mult="0"):
    return [area, area, "AQUA_PD", "Aquaculture production", sp, label, unit, unit, str(year), v, status, mult]


def test_gate_statuses_and_flags():
    rows = [r("USA", "SAL", "Atlantic salmon [Salmo salar]", "T", 2020, "1000"), r("USA", "SAL", "Atlantic salmon [Salmo salar]", "USD", 2020, "4000000"),
            r("USA", "SAL", "Atlantic salmon [Salmo salar]", "T", 2021, "1000"), r("USA", "SAL", "Atlantic salmon [Salmo salar]", "USD", 2021, "4000000"),
            r("USA", "SAL", "Atlantic salmon [Salmo salar]", "T", 2022, "20000", "I"), r("USA", "SAL", "Atlantic salmon [Salmo salar]", "USD", 2022, "4000"),
            r("USA", "OYX", "Cupped oysters nei [Crassostrea spp]", "T", 2022, ""),
            r("USA", "BAD", "Bad [X y]", "T", 2022, "-5"), r("USA", "BAD", "Bad [X y]", "KG", 2021, "5"),
            r("NOR", "SAL", "Atlantic salmon [Salmo salar]", "T", 2022, "0"), r("NOR", "SAL", "Atlantic salmon [Salmo salar]", "T", 2022, "0")]
    c = oecd_clean.classify(frame(rows))
    key = list(zip(c["REF_AREA"], c["SPECIES"], c["UNIT_MEASURE"], c["TIME_PERIOD"]))

    def pick(col, *k):
        vals = [v for kk, v in zip(key, c[col]) if kk == k]
        return vals[0] if len(vals) == 1 else vals
    st = lambda *k: pick("STATUS", *k)
    fl = lambda *k: pick("FLAGS", *k)
    assert st("USA", "SAL", "T", "2020") == "VALID"
    assert st("USA", "SAL", "T", "2021") == "REVIEW" and "CARRIED_FORWARD" in fl("USA", "SAL", "T", "2021")
    f22 = fl("USA", "SAL", "T", "2022")
    assert {"IMPUTED", "JUMP_10X", "PRICE_OUTLIER"} <= set(f22.split("|"))           # 20x jump, $0.0002/kg
    assert st("USA", "OYX", "T", "2022") == "EXCLUDED_BY_DESIGN"
    assert st("USA", "BAD", "T", "2022") == "REJECTED" and pick("REASON", "USA", "BAD", "T", "2022") == "NEGATIVE"
    assert pick("REASON", "USA", "BAD", "KG", "2021") == "UNKNOWN_UNIT"
    assert st("NOR", "SAL", "T", "2022") == ["REJECTED", "REJECTED"]                   # duplicate key
    rep = oecd_clean.report(oecd_clean.classify(frame(rows)))
    assert rep["status"]["REJECTED"] == 4 and rep["flags"]["IMPUTED"] == 1
