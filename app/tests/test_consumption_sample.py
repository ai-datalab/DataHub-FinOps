from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from consumption_sample import load_consumption_sample


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "samples" / "consumption"


def total(filename: str, column: str) -> Decimal:
    with (SAMPLE_DIR / filename).open(encoding="utf-8-sig", newline="") as stream:
        return sum((Decimal(row[column] or "0") for row in csv.DictReader(stream)), Decimal(0))


def test_native_sample_preserves_product_grains_and_currency_bases():
    result = load_consumption_sample()
    coverage = {item["source"]: item for item in result["coverage"]}

    assert result["sample"] is True
    assert result["cowork"]["credits"] == str(total("PersonServiceCreditsMetrics.csv", "Total Copilot Credits used"))
    assert result["studio"]["credits"] == str(
        total("StudioTenantDaily.csv", "Prepaid Consumed Quantity")
        + total("StudioTenantDaily.csv", "Pay as you go Consumed Quantity")
    )
    assert result["github"]["net"] == str(total("GitHubAiUsage.csv", "net_amount"))
    assert result["foundry"]["costByCurrency"] == [{
        "currency": "USD", "cost": str(total("AzureAiSpendDaily.csv", "Cost")),
    }]
    assert result["foundry"]["solutionTotals"][0]["actual"] == str(total("AzureSolutionSpend.csv", "ActualCost"))
    latest = max(row["date"] for row in result["studio"]["days"])
    assert result["studio"]["snapshotMonth"] == latest[:7]
    assert coverage["Cowork / Work IQ weekly credits"]["grain"] == "person × service × policy × week"
    assert coverage["Copilot Studio agent snapshot"]["grain"].endswith("month-to-date")
    assert coverage["Azure AI deployment health"]["grain"] == "latest snapshot × deployment"
    assert "combinedCost" not in result


def test_missing_optional_feeds_are_reported_as_empty(tmp_path):
    result = load_consumption_sample(tmp_path)

    assert all(item["rows"] == 0 and item["status"] == "No sample rows" for item in result["coverage"])
    assert result["cowork"]["credits"] == "0"
    assert result["studio"]["days"] == []
    assert result["github"]["days"] == []
    assert result["foundry"]["costByCurrency"] == []


def test_malformed_numeric_source_data_fails_explicitly(tmp_path):
    path = tmp_path / "PersonServiceCreditsMetrics.csv"
    path.write_text(
        "MetricDate,PersonId,ServiceName,SpendingPolicyId,Session count,Total Copilot Credits used\n"
        "2026-01-05,user-1,Cowork,policy-1,1,NaN\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Non-finite numeric value"):
        load_consumption_sample(tmp_path)


def test_foundry_currency_totals_are_never_combined(tmp_path):
    (tmp_path / "AzureAiSpendDaily.csv").write_text(
        "UsageDate,Meter,Cost,Currency\n"
        "2026-01-05,model-input,1.25,USD\n"
        "2026-01-05,model-output,2.50,EUR\n",
        encoding="utf-8",
    )

    foundry = load_consumption_sample(tmp_path)["foundry"]

    assert foundry["cost"] is None
    assert foundry["currency"] == "Multiple currencies"
    assert foundry["costByCurrency"] == [
        {"currency": "EUR", "cost": "2.50"},
        {"currency": "USD", "cost": "1.25"},
    ]
    assert len(foundry["days"]) == 2


def write_seat_feeds(path: Path, rate_rows: str, github_rows: str = "2026-01-05,alice,copilot,gpt,1,1,0,1,contoso\n") -> None:
    (path / "PeopleMetaData.csv").write_text(
        "PeopleHistoricalId,Organization,IsCopilotLicensed\np1,Ops,true\np2,Ops,true\np3,Ops,false\n", encoding="utf-8")
    (path / "PersonServiceCreditsMetrics.csv").write_text(
        "MetricDate,PersonId,ServiceName,SpendingPolicyId,Session count,Total Copilot Credits used,PeopleHistoricalId\n"
        "2026-01-05,u1,Cowork,pol,1,5,p1\n", encoding="utf-8")
    (path / "GitHubUserMap.csv").write_text("username,plan\nAlice,Copilot Business\nbob,Copilot Business\n", encoding="utf-8")
    (path / "GitHubAiUsage.csv").write_text(
        "date,username,product,model,quantity,gross_amount,discount_amount,net_amount,organization\n" + github_rows,
        encoding="utf-8")
    (path / "LicenseRateCard.csv").write_text(
        "Product,Plan,UnitPrice,Currency,EffectiveFrom,EffectiveTo,Basis\n" + rate_rows, encoding="utf-8")


def test_license_cost_prices_seats_from_the_effective_rate_and_flags_unused_seats(tmp_path):
    write_seat_feeds(tmp_path, (
        "Microsoft 365 Copilot,Microsoft 365 Copilot,30,USD,2025-01-01,,Estimate\n"
        "GitHub Copilot,Copilot Business,19,USD,2025-01-01,2025-12-31,Estimate\n"
        "GitHub Copilot,Copilot Business,21,USD,2026-01-01,,Estimate\n"))

    licenses = load_consumption_sample(tmp_path)["licenses"]
    m365, github = licenses["plans"]

    assert licenses["months"] == ["2026-01"]
    assert (m365["seats"], m365["monthlyRate"], m365["windowCost"]) == (2, "30", "60")
    assert (github["seats"], github["seatsWithoutUsage"], github["monthlyRate"], github["windowCost"],
            github["noUsageCost"]) == (2, 1, "21", "42", "21")
    assert licenses["totals"][0]["monthlyRunRate"] == "102"
    assert licenses["totals"][0]["noUsageCost"] == "21"


def test_license_view_does_not_call_partial_usage_signals_unused_seats(tmp_path):
    write_seat_feeds(tmp_path, "Microsoft 365 Copilot,Microsoft 365 Copilot,30,USD,2025-01-01,,Estimate\n")

    m365 = load_consumption_sample(tmp_path)["licenses"]["plans"][0]

    assert m365["usageSignalComplete"] is False
    assert m365["seatsWithUsage"] == 1
    assert m365["seatsWithoutUsage"] is None and m365["noUsageCost"] is None


def test_license_cost_billed_in_focus_is_excluded_to_avoid_double_counting(tmp_path):
    write_seat_feeds(tmp_path, "GitHub Copilot,Copilot Business,19,USD,2025-01-01,,Billed in FOCUS\n")

    licenses = load_consumption_sample(tmp_path)["licenses"]

    assert licenses["plans"][-1]["status"] == "Billed in FOCUS"
    assert licenses["plans"][-1]["windowCost"] is None
    assert licenses["totals"] == [] and licenses["monthly"] == []


def test_license_seats_without_a_rate_stay_unpriced_and_usage_currency_is_not_assumed(tmp_path):
    write_seat_feeds(tmp_path, "GitHub Copilot,Copilot Enterprise,39,USD,2025-01-01,,Estimate\n")

    licenses = load_consumption_sample(tmp_path)["licenses"]

    assert {plan["status"] for plan in licenses["plans"]} == {"No rate in rate card"}
    assert licenses["totals"] == []
    assert licenses["githubUsageComparable"] is False


@pytest.mark.parametrize("row, message", [
    ("GitHub Copilot,Copilot Business,-1,USD,2025-01-01,,Estimate\n", "must not be negative"),
    ("GitHub Copilot,Copilot Business,19,US,2025-01-01,,Estimate\n", "three-letter code"),
    ("GitHub Copilot,Copilot Business,19,USD,2026-01-01,2025-01-01,Estimate\n", "earlier than EffectiveFrom"),
    ("GitHub Copilot,Copilot Business,19,USD,2025-01-01,,Invoice\n", "Basis"),
])
def test_invalid_rate_card_rows_fail_explicitly(tmp_path, row, message):
    write_seat_feeds(tmp_path, row)

    with pytest.raises(ValueError, match=message):
        load_consumption_sample(tmp_path)


def test_default_sample_license_totals_match_the_rate_card():
    licenses = load_consumption_sample()["licenses"]
    plans = {plan["plan"]: plan for plan in licenses["plans"]}

    assert plans["Microsoft 365 Copilot"]["seats"] == 966
    assert plans["Copilot Business"]["seats"] + plans["Copilot Enterprise"]["seats"] == 219
    assert licenses["totals"][0]["monthlyRunRate"] == "35861.00"
    assert licenses["totals"][0]["reviewSeats"] == 219
