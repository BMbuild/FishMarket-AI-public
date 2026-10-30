"""Prints the raw Census rows behind the trade total so we can see how aggregates appear. Shows no key.
Run from the project folder:  python scripts/census_probe.py"""
from fishmarket import live

for flow, com, val in (("imports", "I_COMMODITY", "GEN_VAL_YR"), ("exports", "E_COMMODITY", "ALL_VAL_YR")):
    rows = live.get_json(f"{live.CENSUS}/{flow}/hs", {"get": f"{com},CTY_CODE,CTY_NAME,{val}", "YEAR": 2023, "MONTH": "12", "COMM_LVL": "HS4", com: "0306", "key": live._key(None)})
    head, data = rows[0], rows[1:]
    iv = head.index(val)
    data = sorted(data, key=lambda r: -float(r[iv] or 0))
    print(f"\n{flow}: {len(data)} rows; header = {head}")
    for r in data[:22]:
        print("  ", r[head.index('CTY_CODE')], "|", r[head.index('CTY_NAME')], "|", r[iv])
    print("   sum of all rows:", sum(float(r[iv] or 0) for r in data))
