"""Mini-wiki: short, sourced, plain-text notes on things NOAA landings and GBIF cannot tell you.
File: data_real/wiki/wiki.md. One `## id | title` block per entry, a few `key: value` lines, then the text.
Search is plain keyword scoring (no model). `python -m fishmarket.wiki check|search "question"`."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data_real" / "wiki" / "wiki.md"
MAX_WORDS = 110
TYPES = {"term", "rules", "method", "gear", "labeling", "handling", "market", "stock", "farming"}


@dataclass
class Entry:
    id: str
    title: str
    type: str
    keywords: list[str]
    species: list[str]
    retrieved: str
    sources: list[str]
    text: str
    extra: dict = field(default_factory=dict)


def _split(s: str) -> list[str]:
    return [x.strip().lower() for x in s.split(",") if x.strip()]


def parse(text: str) -> list[Entry]:
    out = []
    for block in re.split(r"(?m)^## ", text)[1:]:
        head, _, body = block.partition("\n")
        eid, _, title = head.partition("|")
        meta, lines = {}, []
        for ln in body.splitlines():
            m = re.match(r"^(type|keywords|species|retrieved|source):\s*(.*)$", ln)
            if m and not lines:
                meta[m.group(1)] = m.group(2).strip()
            elif ln.strip():
                lines.append(ln.strip())
        out.append(Entry(eid.strip(), title.strip(), meta.get("type", ""), _split(meta.get("keywords", "")), _split(meta.get("species", "")),
                         meta.get("retrieved", ""), meta.get("source", "").split(), " ".join(lines)))
    return out


@lru_cache(maxsize=1)
def load(path: str | None = None) -> dict[str, Entry]:
    entries = parse(Path(path or PATH).read_text(encoding="utf-8"))
    return {e.id: e for e in entries}


def validate(entries: list[Entry] | None = None) -> list[str]:
    """Format problems; an empty list means the wiki is valid."""
    entries = entries if entries is not None else parse(PATH.read_text(encoding="utf-8"))
    errs, seen = [], set()
    for e in entries:
        if not re.fullmatch(r"[a-z0-9_]+", e.id):
            errs.append(f"{e.id!r}: id must be lowercase letters, digits, underscore")
        if e.id in seen:
            errs.append(f"{e.id}: duplicate id")
        seen.add(e.id)
        if e.type not in TYPES:
            errs.append(f"{e.id}: type must be one of {sorted(TYPES)}")
        if not e.sources or not all(re.match(r"https://[^\s]+$", s) for s in e.sources):
            errs.append(f"{e.id}: needs at least one https source link")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.retrieved):
            errs.append(f"{e.id}: retrieved must be YYYY-MM-DD")
        if not e.keywords:
            errs.append(f"{e.id}: needs keywords")
        if e.type == "stock" and not e.species:
            errs.append(f"{e.id}: stock entries need species aliases")
        n = len(e.text.split())
        if n < 15 or n > MAX_WORDS:
            errs.append(f"{e.id}: text is {n} words (keep 15 to {MAX_WORDS})")
    return errs


def _has(q: str, k: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", q) is not None


STOCK_WORDS = ("sustainable", "sustainability", "sustainable choice", "good choice", "overfished", "overfishing", "stock status", "eco-friendly", "ok to buy", "okay to buy")

RULE_WORDS = ("rules", "regulations", "regulated", "managed", "management", "quota", "quotas", "size limit", "catch limit", "allowed to", "legal")


def score(e: Entry, question: str, species: list[str] | None = None) -> int:
    q = " " + question.lower() + " "
    sc = sum(max(3, round(len(k.split()) ** 1.5 * 2)) for k in e.keywords if _has(q, k))
    sp = [s.lower() for s in (species or [])]
    # a resolved species must match an alias exactly ("pacific cod" is not "cod"); free text is used only when nothing was resolved
    if e.species and ((sp and any(s == a for a in e.species for s in sp)) or (not sp and any(_has(q, a) for a in e.species))):
        sc += 3                       # a stock entry matches its own species; it needs a status/rules word as well to win
    if sp and e.species and not any(s == a for a in e.species for s in sp):
        return min(sc, 2)                         # an entry about a different species never answers for this one
    if e.type == "stock" and any(_has(q, w) for w in STOCK_WORDS + RULE_WORDS):
        sc += 4                                   # generic status wording ("is X sustainable?") counts for a stock entry
    elif e.type in ("stock", "farming") and e.species and not any(_has(q, k) for k in e.keywords):
        sc = min(sc, 2)
    return sc


def search(question: str, species: list[str] | None = None, k: int = 2, min_score: int = 3, path: str | None = None) -> list[tuple[int, Entry]]:
    ranked = sorted(((score(e, question, species), e) for e in load(path).values()), key=lambda t: -t[0])
    return [(s, e) for s, e in ranked[:k] if s >= min_score]


def best_score(question: str, species: list[str] | None = None) -> int:
    r = search(question, species, k=1, min_score=0)
    return r[0][0] if r else 0


def stale(as_of: str, max_days: int = 365, entries=None) -> list[str]:
    """Entries read more than max_days before as_of (YYYY-MM-DD). Stock status and rules go out of date."""
    from datetime import date
    ref = date.fromisoformat(as_of)
    out = []
    for e in (entries if entries is not None else load().values()):
        try:
            age = (ref - date.fromisoformat(e.retrieved)).days
        except ValueError:
            continue
        if age > max_days:
            out.append(f"{e.id}: read {e.retrieved}, {age} days before {as_of}; re-check {e.sources[0]}")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        errs = validate()
        as_of = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--as-of=")), None)
        old = stale(as_of) if as_of else []
        print("\n".join(errs) if errs else f"OK: {len(load())} entries, {sum(len(e.text.split()) for e in load().values())} words")
        if old:
            print("STALE (re-read the source and update):\n  " + "\n  ".join(old))
        sys.exit(1 if errs else 0)
    for s, e in search(" ".join(sys.argv[2:])):
        print(f"[{s}] {e.title}\n  {e.text}\n  Source: {' '.join(e.sources)} (read {e.retrieved})\n")
