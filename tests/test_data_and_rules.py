import subprocess
import sys
from pathlib import Path

from fishmarket.config import ROOT


def test_data_validates():
    out = subprocess.run([sys.executable, "fishmarket_data/tools/validate_data.py", "fishmarket_data"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-800:]
    assert "0 failure(s)" in out.stdout


def test_no_tests_only_reads():
    """Rule 3: nothing under src/ or app/ may mention tests_only."""
    offenders = []
    for folder in ("src", "app"):
        for p in (ROOT / folder).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".md", ".json", ".toml", ".txt"}:
                if "tests_only" in p.read_text(errors="ignore"):
                    offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, offenders


def test_no_clock_calls_in_pipeline_logic():
    """Rule 2: the date is fixed. Logging timestamps live only in events.py and llm.py."""
    allowed = {"events.py", "llm.py", "handoff.py"}   # handoff.py stamps collected_at (ingestion date), which never feeds a calculation
    bad = []
    for p in (ROOT / "src" / "fishmarket").rglob("*.py"):
        text = p.read_text()
        if p.name not in allowed and ("datetime.now" in text or "date.today" in text or "Timestamp.now" in text):
            bad.append(p.name)
    assert not bad, bad


def test_only_llm_module_imports_the_sdk():
    for p in (ROOT / "src").rglob("*.py"):
        if p.name != "llm.py":
            assert "import anthropic" not in p.read_text() and "from anthropic" not in p.read_text(), p.name
