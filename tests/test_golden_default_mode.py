"""On 2026-10-29 `python -m evals.run_golden --mix dev` run without --mode defaulted to auto, found the key in
.env and made 82 paid Haiku calls ($0.052) before it was stopped. The golden pass must cost nothing unless the
caller asks for a paid mode by name."""
import pytest

from evals import run_golden


def test_no_mode_runs_fake_and_never_builds_a_real_client(monkeypatch, tmp_path, capsys):
    def no_real_client(*a, **k):
        raise AssertionError("run_golden built a real LLM client without being asked")

    monkeypatch.setattr(run_golden, "LLM", no_real_client)
    monkeypatch.setattr(run_golden, "ROOT", tmp_path)
    assert run_golden.main(["--mix", "dev", "--cases", "G01"]) == 0
    assert "cost $0.0000" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["auto", "live", "replay"])
def test_paid_or_cached_modes_still_work_when_asked_by_name(mode):
    assert run_golden.parse_args(["--mode", mode]).mode == mode


def test_the_default_mode_is_fake():
    assert run_golden.parse_args([]).mode == "fake"
