"""Free-text note handling. The note is untrusted data: it is cleaned, scanned and passed (cleaned) only to the
analyst and the summary agent. It never changes a number, a direction, a rating or a tag."""
from __future__ import annotations

import hashlib
import re

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules)",
    r"disregard (all |any |the )?(previous|prior|above|earlier)",
    r"\bsystem\s*:", r"you are now\b", r"reveal your\b", r"print your\b", r"show your (system )?prompt",
    r"set (the )?(trust|confidence)\b", r"admin mode", r"developer mode", r"new instructions",
    r"report that this fish is", r"say (that )?the data is",
]
OUT_OF_SCOPE = {
    "lottery": "lottery numbers", "tax": "tax advice", "legal advice": "legal advice", "lawyer": "legal advice",
    "loan": "loans or financing", "insurance": "insurance", "medical": "medical advice",
    "buy a boat": "buying a boat", "buying a boat": "buying a boat", "second boat": "buying a boat",
    "hire": "hiring", "visa": "visas", "stock": "stock trading", "crypto": "crypto",
}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{6,}\d)(?!\d)")
_TAGS = re.compile(r"<[^>]{0,200}>")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise(text: str | None, max_chars: int = 1000) -> dict:
    raw = text or ""
    t = _CTRL.sub(" ", raw)
    t = _TAGS.sub(" ", t)
    t = _EMAIL.sub("[redacted]", t)
    t = _PHONE.sub("[redacted]", t)
    t = re.sub(r"\s+", " ", t).strip()
    truncated = len(t) > max_chars
    if truncated:
        t = t[:max_chars].rstrip()
    return {"text": t, "truncated": truncated, "length": len(t), "redacted": "[redacted]" in t}


def matched_injection(text: str) -> list[str]:
    """Phrases in `text` that look like instructions to an AI (verbatim matches, lower-cased)."""
    out = []
    for p in INJECTION_PATTERNS:
        for m in re.finditer(p, text, re.I):
            out.append(m.group(0).lower())
    return out


def scan(text: str, brief_species: list[str], brief_region: str, species_names: list[str],
         region_names: list[str]) -> dict:
    """Flags only; never decisions. Returns {flags, injection_phrases, out_of_scope, conflicts}."""
    low = text.lower()
    phrases = matched_injection(text)
    oos = sorted({label for kw, label in OUT_OF_SCOPE.items() if re.search(rf"\b{re.escape(kw)}", low)})
    conflicts = []
    for s in species_names:
        if re.search(rf"\b{re.escape(s.lower())}\b", low) and s not in brief_species:
            conflicts.append(s)
    for r in region_names:
        if re.search(rf"\b{re.escape(r.lower())}\b", low) and r != brief_region:
            conflicts.append(r)
    flags = []
    if phrases:
        flags.append("untrusted_text_ignored")
    if oos:
        flags.append("note_out_of_scope")
    if conflicts:
        flags.append("profile_conflict")
    return {"flags": flags, "injection_phrases": phrases, "out_of_scope": oos, "conflicts": conflicts}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def block(text: str) -> str | None:
    """The only form in which the note reaches a model."""
    return f"<user_note>{text}</user_note>" if text else None


# ---- facts the scenario can use, read out of the note by Python (never by a model) -------------------------
import csv as _csv
from functools import lru_cache as _lru
from pathlib import Path as _Path

_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "a couple of": 2, "a few": 3, "a": 1}
_NUM = r"(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a couple of|a few)"
_STORE_MONTHS = re.compile(r"(?:freezer|storage|cooler|tank|space|hold|keep|store)[^.?!]{0,50}?\b" + _NUM + r"\s*(months?|weeks?)"
                           r"|\b" + _NUM + r"\s*(months?|weeks?)\s*(?:of|worth of)\s*(?:catch|storage|product|fish|crab|freezer)", re.I)
_VOLUME = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|thousand|million)?\s*(?:lb|lbs|pounds)\b(?:\s*(?:a|per|each|every)\s*(day|week|month|year|season))?", re.I)
_PER_MONTH = {"day": 30.0, "week": 52 / 12, "month": 1.0, "year": 1 / 12, "season": 1 / 6, None: 1.0}
_SENT_Q = re.compile(r"[^.!?\n]{8,300}\?")


@_lru(maxsize=2)
def _cues(data_dir: str) -> list[tuple[str, str, re.Pattern]]:
    out = []
    with open(_Path(data_dir) / "registry" / "note_cues.csv", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#") or line.startswith("field,"):
                continue
            field, value, pattern = line.split(",", 2)       # the pattern is everything after the second comma
            out.append((field, value, re.compile(pattern, re.I)))
    return out


@_lru(maxsize=2)
def _places(data_dir: str) -> list[tuple[str, str]]:
    with open(_Path(data_dir) / "registry" / "place_regions.csv", newline="", encoding="utf-8") as f:
        rows = list(_csv.DictReader(f))
    return sorted(((r["place"], r["region"]) for r in rows), key=lambda x: -len(x[0]))


def _num(word: str) -> float:
    w = word.lower()
    return float(_WORDNUM[w]) if w in _WORDNUM else float(w)


def extract(text: str, species_names: list[str], region_names: list[str], data_dir) -> dict:
    """What the note says, as form fields. Each found item also gets a plain line for "What we took from your note".
    Python only: the patterns live in fishmarket_data/registry/note_cues.csv and place_regions.csv."""
    t = text or ""
    low = t.lower()
    out: dict = {"species": [], "region": None, "storage": None, "storage_months": None, "volume_lb_per_month": None,
                 "segment": None, "goal": None, "experience": None, "constraints": [], "asks": [], "questions": [], "taken": []}
    if not t.strip():
        return out
    masked = low
    for s in sorted(set(species_names), key=len, reverse=True):
        m = re.search(rf"(?<![a-z]){re.escape(s.lower())}(?:e?s)?(?![a-z])", masked)
        if m:
            out["species"].append(s)
            masked = masked[:m.start()] + " " * (m.end() - m.start()) + masked[m.end():]
    for r in region_names:
        if re.search(rf"\b{re.escape(r.lower())}\b", low):
            out["region"] = r
            break
    if out["region"] is None:
        for place, r in _places(str(data_dir)):
            if re.search(rf"\b{re.escape(place)}\b", low):
                out["region"] = r
                break
    for field, value, rx in _cues(str(data_dir)):
        if not rx.search(t):
            continue
        if field in ("constraints", "asks"):
            if value not in out[field]:
                out[field].append(value)
        elif out.get(field) is None:
            out[field] = value
    m = _STORE_MONTHS.search(t)
    if m:
        n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        months = _num(n) * (1.0 if unit.lower().startswith("month") else 7 / 30)
        if 0 < months <= 24:
            out["storage_months"] = round(months, 1)
    m = _VOLUME.search(t)
    if m:
        v = float(m.group(1).replace(",", "")) * {"k": 1e3, "thousand": 1e3, "million": 1e6}.get((m.group(2) or "").lower(), 1.0)
        v *= _PER_MONTH[(m.group(3) or "").lower() or None]
        if v > 0:
            out["volume_lb_per_month"] = round(v)
    out["questions"] = [re.sub(r"\s+", " ", q).strip() for q in _SENT_Q.findall(t)][:3]
    tk = out["taken"]
    if out["species"]:
        tk.append("Species: " + ", ".join(out["species"]))
    if out["region"]:
        tk.append(f"Region: {out['region']}")
    if out["storage"]:
        tk.append("Storage: " + {"none": "no storage", "frozen": "freezer", "chilled": "chilled or live holding"}[out["storage"]]
                  + (f", about {out['storage_months']:g} months" if out["storage_months"] else ""))
    if out["volume_lb_per_month"]:
        tk.append(f"Volume: about {out['volume_lb_per_month']:,} lb a month")
    if out["segment"]:
        tk.append(f"Customers: {out['segment'].replace('_', ' ')}")
    if out["goal"]:
        tk.append(f"Goal: {out['goal']}")
    if out["experience"]:
        tk.append(f"Experience: {out['experience']}")
    if out["constraints"]:
        tk.append("Constraints: " + ", ".join(out["constraints"]))
    if out["asks"]:
        tk.append("You also asked about: " + ", ".join(out["asks"]))
    if out["questions"]:
        tk.append("Question: " + out["questions"][0])
    return out
