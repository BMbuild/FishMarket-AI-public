"""Data-origin tags and the guard that stops real and synthetic values from being combined."""
from __future__ import annotations

from dataclasses import dataclass

REAL, SYNTHETIC, DERIVED = "REAL", "SYNTHETIC", "DERIVED"
PILL = {"REAL_NOAA": "REAL (NOAA)", "REAL_GBIF": "REAL (GBIF)", "REAL_OTHER": "REAL (other public source)", "SYNTHETIC": "SYNTHETIC",
        "DERIVED": "DERIVED", "TEST_FIXTURE": "TEST FIXTURE (synthetic)",
        "WEB_TRUSTED": "WEB (trusted source, quoted)", "WEB_OPEN": "WEB (open web, quoted)"}
SYNTH_SENTENCE = "Illustrative, generated from NOAA annual levels, not a real market price."


class MixedOriginError(Exception):
    pass


@dataclass(frozen=True)
class Tagged:
    value: float
    origin: str            # one of REAL, SYNTHETIC
    anchored_to: str = ""


def is_real(origin: str) -> bool:
    return origin.startswith("REAL")


def family(origin: str) -> str:
    return REAL if is_real(origin) else SYNTHETIC if origin in ("SYNTHETIC", "TEST_FIXTURE") else origin


def combine(items: list[Tagged], fn):
    """Apply an aggregate (sum, mean, rank...) across values. Refuses to mix real and synthetic operands."""
    fams = {family(i.origin) for i in items}
    if len(fams) > 1:
        raise MixedOriginError(f"cannot combine {sorted(fams)} values in one calculation")
    out = fn([i.value for i in items])
    return Tagged(out, items[0].origin if items else REAL)


def anchor(real_value: float, dataset_id: str) -> Tagged:
    """A real number used ONLY as a scale for generated data. Everything computed from it is SYNTHETIC."""
    return Tagged(real_value, SYNTHETIC, anchored_to=dataset_id)


def check_claims(claims) -> None:
    """Every claim must declare the origins of its inputs; mixing real with synthetic is a bug."""
    for c in claims:
        fams = {family(o) for o in c.inputs_origin}
        if len(fams) > 1:
            raise MixedOriginError(f"claim {c.id} mixes origins {sorted(fams)}")
