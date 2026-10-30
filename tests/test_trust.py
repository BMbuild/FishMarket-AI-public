import pytest

from fishmarket.trust import compute_trust

CASES = [
    # flags, usable tiers, expected rating
    (set(), ["A", "B", "C"], "high"),
    (set(), ["B", "C"], "high"),
    ({"single_source"}, ["A"], "medium"),
    ({"single_source"}, ["B"], "medium"),
    ({"single_source"}, ["C"], "low"),                          # only lower-trust source
    (set(), ["C", "D"], "low"),
    (set(), [], "low"),
    ({"fallback_sample_data", "single_source"}, ["D"], "low"),
    ({"source_disagreement"}, ["A", "C"], "low"),
    ({"source_disagreement", "stale_data", "unit_mismatch"}, ["A", "C"], "low"),   # low beats medium
    ({"unit_mismatch"}, ["A", "B"], "medium"),
    ({"outlier"}, ["A", "B"], "medium"),
    ({"duplicates", "missing_values", "date_range"}, ["A", "B"], "medium"),
    ({"aging_data"}, ["A", "B"], "medium"),
    ({"stale_data"}, ["A", "C"], "medium"),
    ({"stale_data", "single_source"}, ["A"], "medium"),
    ({"schema"}, ["A", "B"], "medium"),
]


@pytest.mark.parametrize("flags,tiers,rating", CASES)
def test_trust_rules(flags, tiers, rating):
    out = compute_trust(flags, tiers)
    assert out["rating"] == rating
    assert out["reasons"] and all(isinstance(r, str) for r in out["reasons"])


def test_reasons_contain_no_digits():
    """Reasons feed the summary agent; digits there would trip the summary's number check."""
    for flags, tiers, _ in CASES:
        assert not any(ch.isdigit() for r in compute_trust(flags, tiers)["reasons"] for ch in r)


def test_trust_is_pure():
    f = {"single_source"}
    compute_trust(f, ["A"])
    assert f == {"single_source"}
