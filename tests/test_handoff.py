import csv
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fishmarket.handoff import FOSSPlan, Handoff, agent_b, analyst, collect, validate


SOURCE_URL = "https://apps-st.fisheries.noaa.gov/foss/f?p=215:200"
COLLECTED_AT = date(2026, 10, 15)


def write_export(path, rows):
    headers = [
        "Year", "State", "NMFS Name", "Pounds", "Metric Tons", "Dollars",
        "Confidentiality", "Collection", "Scientific Name", "Tsn", "Source",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        file.write(",,,,,,,,,,\n")
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def noaa_row(**overrides):
    row = {
        "Year": "2022",
        "State": "LOUISIANA",
        "NMFS Name": "SHRIMP, BROWN",
        "Pounds": "11,873,802",
        "Metric Tons": "5,386",
        "Dollars": "15,741,883",
        "Confidentiality": "Public",
        "Collection": "Commercial",
        "Scientific Name": "Penaeus aztecus",
        "Tsn": "95605",
        "Source": "GULFFIN",
    }
    row.update(overrides)
    return row


def plan_for(path, **overrides):
    return FOSSPlan(
        csv_path=path,
        species="brown shrimp",
        region="Louisiana",
        source_url=SOURCE_URL,
        collected_at=COLLECTED_AT,
        **overrides,
    )


def test_collect_handles_noaa_export_preamble_and_builds_verified_handoff(tmp_path):
    path = tmp_path / "FOSS_landings.csv"
    write_export(path, [noaa_row()])

    handoff = validate(collect(plan_for(path, expected_years=[2022])), range(2022, 2023))
    result = agent_b(handoff.model_dump(mode="json"))

    assert handoff.species == "brown shrimp"
    assert handoff.region == "Louisiana"
    assert handoff.observations[0].period == "2022"
    assert handoff.observations[0].source_id == "GULFFIN"
    assert handoff.observations[0].unit == "USD/lb"
    assert handoff.observations[0].collected_at == COLLECTED_AT
    assert handoff.observations[0].price.quantize(Decimal("0.0001")) == Decimal("1.3258")
    assert result["volume_weighted_average"].quantize(Decimal("0.0001")) == Decimal("1.3258")
    assert "not real-time quotes" in result["caveats"][0]
    assert analyst(handoff) == (
        "brown shrimp/Louisiana 2022-2022: weighted avg 1.33 USD/lb over 1 year(s). "
        "Caveats: ['Annual aggregated NOAA commercial landings; not real-time quotes.', "
        "'collected_at is the local ingestion date; the export does not provide its retrieval date.']"
    )


def test_validate_requires_exact_year_set():
    observation = {
        "price": "1.25",
        "unit": "USD/lb",
        "period": "2022",
        "source_url": SOURCE_URL,
        "source_id": "GULFFIN",
        "collected_at": "2026-10-26",
        "pounds": "100",
        "dollars": "125",
    }
    handoff = Handoff(species="brown shrimp", region="Louisiana", observations=[observation])

    assert validate(handoff, range(2022, 2023)) is handoff
    with pytest.raises(ValueError, match=r"Period mismatch: found \[2022\]; expected \[2021, 2022\]"):
        validate(handoff, range(2021, 2023))


def test_collect_excludes_recreational_and_non_matching_rows(tmp_path):
    path = tmp_path / "FOSS_landings.csv"
    write_export(path, [
        noaa_row(Collection="Recreational"),
        noaa_row(State="TEXAS"),
        noaa_row(**{"NMFS Name": "SHRIMP, WHITE"}),
    ])

    with pytest.raises(ValueError, match="no public commercial observations"):
        collect(plan_for(path))


def test_collect_excludes_non_public_matching_rows(tmp_path):
    path = tmp_path / "FOSS_landings.csv"
    write_export(path, [noaa_row(Confidentiality="Confidential")])

    with pytest.raises(ValueError, match="no public commercial observations"):
        collect(plan_for(path))


def test_handoff_rejects_missing_expected_year(tmp_path):
    path = tmp_path / "FOSS_landings.csv"
    write_export(path, [noaa_row()])

    with pytest.raises(ValidationError, match="missing expected periods"):
        collect(plan_for(path, expected_years=[2021, 2022]))


def test_agent_b_rejects_empty_or_incomplete_payload():
    with pytest.raises(ValidationError):
        agent_b({"species": "brown shrimp", "region": "Louisiana", "observations": []})

    observation = {
        "price": "1.25",
        "unit": "USD/lb",
        "period": "2022",
        "source_url": SOURCE_URL,
        "source_id": "GULFFIN",
        "collected_at": "2026-10-26",
        "pounds": "100",
        "dollars": "125",
    }
    with pytest.raises(ValidationError, match="missing expected periods"):
        Handoff(
            species="brown shrimp",
            region="Louisiana",
            observations=[observation],
            expected_periods=["2023"],
        )


def test_agent_b_rejects_untrusted_source_url_and_inconsistent_price():
    payload = {
        "species": "brown shrimp",
        "region": "Louisiana",
        "expected_periods": ["2022"],
        "observations": [{
            "price": "1.00",
            "unit": "USD/lb",
            "period": "2022",
            "source_url": "https://example.com/export.csv",
            "source_id": "GULFFIN",
            "collected_at": "2026-10-26",
            "pounds": "100",
            "dollars": "200",
        }],
    }

    with pytest.raises(ValidationError, match="NOAA Fisheries"):
        agent_b(payload)

    payload["observations"][0]["source_url"] = "https://evilfisheries.noaa.gov/export.csv"
    with pytest.raises(ValidationError, match="NOAA Fisheries"):
        agent_b(payload)

    payload["observations"][0]["source_url"] = SOURCE_URL
    with pytest.raises(ValidationError, match="price must equal dollars divided by pounds"):
        agent_b(payload)


def test_handoff_rejects_duplicate_periods(tmp_path):
    path = tmp_path / "FOSS_landings.csv"
    write_export(path, [noaa_row(), noaa_row(Source="OTHER")])

    with pytest.raises(ValidationError, match="duplicate observation periods"):
        collect(plan_for(path))


def test_collect_rejects_malformed_thousands_grouping(tmp_path):
    path = tmp_path / "FOSS_landings.csv"
    write_export(path, [noaa_row(Pounds="1,2,3")])

    with pytest.raises(ValueError, match="invalid Pounds value"):
        collect(plan_for(path))
