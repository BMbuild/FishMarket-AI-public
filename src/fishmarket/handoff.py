"""Validated handoff for NOAA FOSS annual commercial landings exports."""
from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


NOAA_LANDINGS_URL = "https://apps-st.fisheries.noaa.gov/foss/f?p=215:200"


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: Decimal = Field(gt=0)
    unit: Literal["USD/lb"]
    period: str = Field(pattern=r"^\d{4}$")
    source_url: HttpUrl
    source_id: str = Field(min_length=1)
    collected_at: date
    pounds: Decimal = Field(gt=0)
    dollars: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def price_matches_value_and_weight(self) -> "Observation":
        if abs(self.price - self.dollars / self.pounds) > Decimal("0.00000001"):
            raise ValueError("price must equal dollars divided by pounds")
        return self

    @field_validator("source_url")
    @classmethod
    def require_noaa_source(cls, value: HttpUrl) -> HttpUrl:
        host = str(value.host).casefold()
        if value.scheme != "https" or not (
            host == "fisheries.noaa.gov" or host.endswith(".fisheries.noaa.gov")
        ):
            raise ValueError("source_url must be an HTTPS NOAA Fisheries URL")
        return value


class Handoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    species: str = Field(min_length=1)
    region: str = Field(min_length=1)
    observations: list[Observation] = Field(min_length=1)
    expected_periods: list[str] = Field(default_factory=list)
    indices: dict[str, Decimal] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_series(self) -> "Handoff":
        periods = [item.period for item in self.observations]
        if len(periods) != len(set(periods)):
            raise ValueError("duplicate observation periods are not allowed")
        missing = sorted(set(self.expected_periods) - set(periods))
        if missing:
            raise ValueError(f"missing expected periods: {missing}")
        return self


class FOSSPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    csv_path: Path
    species: str = Field(min_length=1)
    region: str = Field(min_length=1)
    # Supplied by the caller (rule 2: no clock calls in pipeline logic).
    collected_at: date
    source_url: HttpUrl = NOAA_LANDINGS_URL
    expected_years: list[int] = Field(default_factory=list)

    @field_validator("source_url")
    @classmethod
    def require_noaa_source(cls, value: HttpUrl) -> HttpUrl:
        host = str(value.host).casefold()
        if value.scheme != "https" or not (
            host == "fisheries.noaa.gov" or host.endswith(".fisheries.noaa.gov")
        ):
            raise ValueError("source_url must be an HTTPS NOAA Fisheries URL")
        return value


def _normalise_name(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _number(value: str, column: str) -> Decimal:
    cleaned = value.strip()
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", cleaned):
        raise ValueError(f"invalid {column} value: {value!r}")
    try:
        number = Decimal(cleaned.replace(",", ""))
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"invalid {column} value: {value!r}") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{column} must be a positive number")
    return number


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.reader(file))
    header_index = next((i for i, row in enumerate(rows) if any(cell.strip() for cell in row)), None)
    if header_index is None:
        raise ValueError("CSV is empty")
    headers = [cell.strip() for cell in rows[header_index]]
    required = {"Year", "State", "NMFS Name", "Pounds", "Dollars", "Confidentiality", "Collection", "Source"}
    missing = required - set(headers)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
    with path.open(newline="", encoding="utf-8-sig") as file:
        lines = file.readlines()[header_index:]
    return list(csv.DictReader(lines))


def collect(plan: FOSSPlan | dict) -> Handoff:
    """Convert matching public commercial rows into validated annual observations."""
    parsed_plan = FOSSPlan.model_validate(plan)
    species_key = _normalise_name(parsed_plan.species)
    region_key = _normalise_name(parsed_plan.region)
    observations: list[Observation] = []
    excluded = 0

    for row in _rows(parsed_plan.csv_path):
        if _normalise_name(row["NMFS Name"]) != species_key:
            continue
        if _normalise_name(row["State"]) != region_key:
            continue
        if row["Collection"].strip().casefold() != "commercial":
            continue
        if row["Confidentiality"].strip().casefold() != "public":
            excluded += 1
            continue

        pounds = _number(row["Pounds"], "Pounds")
        dollars = _number(row["Dollars"], "Dollars")
        observations.append(Observation(
            price=dollars / pounds,
            unit="USD/lb",
            period=row["Year"].strip(),
            source_url=parsed_plan.source_url,
            source_id=row["Source"].strip(),
            collected_at=parsed_plan.collected_at,
            pounds=pounds,
            dollars=dollars,
        ))

    if not observations:
        raise ValueError("no public commercial observations matched the requested species and region")

    caveats = [
        "Annual aggregated NOAA commercial landings; not real-time quotes.",
        "collected_at is the local ingestion date; the export does not provide its retrieval date.",
    ]
    if excluded:
        caveats.append(f"Excluded {excluded} matching non-public row(s).")
    return Handoff(
        species=parsed_plan.species,
        region=parsed_plan.region,
        observations=observations,
        expected_periods=[str(year) for year in parsed_plan.expected_years],
        caveats=caveats,
    )


def validate(handoff: Handoff, years: Iterable[int]) -> Handoff:
    """Reject missing, extra, duplicate, or incompatible annual observations."""
    parsed = Handoff.model_validate(handoff)
    if not parsed.observations:
        raise ValueError("No observations")
    if len({item.unit for item in parsed.observations}) > 1:
        raise ValueError("Mixed units")
    if any(item.pounds is None or item.pounds <= 0 for item in parsed.observations):
        raise ValueError("Missing or non-positive weight")
    found = {int(item.period) for item in parsed.observations}
    expected = set(years)
    if found != expected:
        raise ValueError(f"Period mismatch: found {sorted(found)}; expected {sorted(expected)}")
    return parsed


def agent_b(payload: Handoff | dict) -> dict:
    """Validate Agent A's structured payload and compute a volume-weighted annual price."""
    handoff = Handoff.model_validate(payload)
    if not handoff.expected_periods:
        raise ValueError("expected periods are required for analyst validation")
    handoff = validate(handoff, (int(period) for period in handoff.expected_periods))
    units = {item.unit for item in handoff.observations}
    if len(units) != 1:
        raise ValueError("mixed units: convert before analysis")
    total_pounds = sum((item.pounds for item in handoff.observations), Decimal(0))
    total_dollars = sum((item.dollars for item in handoff.observations), Decimal(0))
    return {
        "species": handoff.species,
        "region": handoff.region,
        "periods": [item.period for item in handoff.observations],
        "observation_count": len(handoff.observations),
        "volume_weighted_average": total_dollars / total_pounds,
        "unit": next(iter(units)),
        "caveats": handoff.caveats,
    }


def analyst(payload: Handoff | dict) -> str:
    """Return Agent B's checked, human-readable handoff result."""
    result = agent_b(payload)
    years = sorted({int(period) for period in result["periods"]})
    average = result["volume_weighted_average"]
    return (
        f"{result['species']}/{result['region']} {years[0]}-{years[-1]}: "
        f"weighted avg {average:.2f} {result['unit']} over {len(years)} year(s). "
        f"Caveats: {result['caveats']}"
    )


NOAA_REAL_SOURCE_URL = "https://apps-st.fisheries.noaa.gov/ods/foss/landings/"


def from_series(series, species: str, region: str, source_id: str = "NOAA-FOSS-LANDINGS") -> Handoff:
    """Bridge for the real-data page: turn an annual series (columns year, pounds, dollars) into a validated Handoff.
    Expected periods are every year from first to last, so gaps are reported instead of hidden (see gap_report)."""
    today = date.today()
    obs = [Observation(price=Decimal(str(r.dollars)) / Decimal(str(r.pounds)), unit="USD/lb", period=str(int(r.year)),
                       source_url=NOAA_REAL_SOURCE_URL, source_id=source_id, collected_at=today,
                       pounds=Decimal(str(r.pounds)), dollars=Decimal(str(r.dollars)))
           for r in series.itertuples()]
    return Handoff(species=species, region=region, observations=obs,
                   caveats=["Annual aggregated NOAA commercial landings; not real-time quotes."])


def gap_report(handoff: Handoff) -> dict:
    """Missing years between the first and last observation. Does not raise; the caller decides what to show."""
    years = sorted(int(o.period) for o in handoff.observations)
    missing = [y for y in range(years[0], years[-1] + 1) if y not in set(years)]
    return {"first": years[0], "last": years[-1], "count": len(years), "missing": missing, "complete": not missing}
