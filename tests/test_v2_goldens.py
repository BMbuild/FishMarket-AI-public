"""All 53 golden cases through the real pipeline with the scripted model. Python's numbers must equal the
expected block, which was computed independently by the dataset's reference calculations."""
import pytest

from evals.golden_checks import check_case
from fishmarket import loader
from fishmarket.config import DEFAULT
from fishmarket.fake_agents import fake_llm
from fishmarket.pipeline import run


@pytest.mark.parametrize("idx", range(53))
def test_golden_case(idx, golden, cfg):
    g = golden[idx]
    ov = loader.overrides_from_manifest(DEFAULT, g["planted_cases"]) if g["planted_cases"] else None
    llm = fake_llm(cfg, ov)
    res = run(g["profile"], ov, llm=llm, cfg=cfg, save=False)
    assert check_case(g, res, [x["user"] for x in llm.log]) == [], g["name"]
    assert res["calls"] <= 5


def test_there_are_53_goldens(golden):
    assert len(golden) == 53 and len({g["case_id"] for g in golden}) == 53
