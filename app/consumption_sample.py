"""Fixture-backed, source-native Consumption Central summaries for the local prototype."""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from licenses import build_license_view


ROOT = Path(__file__).resolve().parent
SAMPLE_DIR = ROOT.parent / "samples" / "consumption"
ZERO = Decimal(0)
REQUIRED_COLUMNS = {
    "PersonServiceCreditsMetrics.csv": {"MetricDate", "PersonId", "ServiceName", "SpendingPolicyId", "Session count", "Total Copilot Credits used"},
    "SpendingPolicyMetadata.csv": {"SpendingPolicyId", "Name"},
    "StudioTenantDaily.csv": {"Usage Date", "Prepaid Consumed Quantity", "Pay as you go Consumed Quantity"},
    "StudioPerAgent.csv": {"Agent Id", "AI Feature/Billable Feature", "Billed credit", "Non-billed credit"},
    "StudioPerUser.csv": {"User Email", "Credits used"},
    "GitHubAiUsage.csv": {"date", "username", "product", "model", "quantity", "gross_amount", "discount_amount", "net_amount", "organization"},
    "AzureAiSpendDaily.csv": {"UsageDate", "Meter", "Cost", "Currency"},
    "AzureAiTokensDaily.csv": {"Date", "Metric", "Value"},
    "AzureSolutionSpend.csv": {"UsageDate", "Currency", "ActualCost", "AmortizedCost", "AllocationStatus", "ServiceCategory", "Application"},
    "AzureDeploymentHealth.csv": {"SnapshotDate", "DeploymentName", "DeploymentId", "Requests", "ServerErrors5xx", "Throttles429"},
    "PeopleMetaData.csv": {"PeopleHistoricalId", "IsCopilotLicensed"},
    "GitHubUserMap.csv": {"username", "plan"},
    "LicenseRateCard.csv": {"Product", "Plan", "UnitPrice", "Currency", "EffectiveFrom"},
}


def _read(directory: Path, filename: str) -> list[dict[str, str]]:
    path = directory / filename
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{filename} has missing or duplicate column names.")
        missing = REQUIRED_COLUMNS[filename] - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{filename} is missing required columns: {', '.join(sorted(missing))}.")
        return [{key: value or "" for key, value in row.items()} for row in reader]


def _number(row: dict[str, str], column: str) -> Decimal:
    value = row.get(column, "").strip()
    if not value:
        return ZERO
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid numeric value in {column}: {value!r}.") from error
    if not result.is_finite():
        raise ValueError(f"Non-finite numeric value in {column}: {value!r}.")
    return result


def _iso_date(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("A sample row has no date.")
    try:
        return datetime.fromisoformat(value[:10]).date().isoformat()
    except ValueError:
        try:
            return datetime.strptime(value, "%m/%d/%Y %I:%M:%S %p").date().isoformat()
        except ValueError as error:
            raise ValueError(f"Unsupported sample date: {value!r}.") from error


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _group(rows: list[dict[str, str]], key: str, amount: str) -> list[dict[str, str]]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in rows:
        totals[row.get(key, "").strip() or "(Not recorded)"] += _number(row, amount)
    return [
        {"name": name, "value": _decimal_text(total)}
        for name, total in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]


def _sum(rows: list[dict[str, str]], column: str) -> Decimal:
    return sum((_number(row, column) for row in rows), ZERO)


def load_consumption_sample(directory: Path = SAMPLE_DIR) -> dict:
    """Load optional product feeds without blending their units or native grains."""
    cowork = _read(directory, "PersonServiceCreditsMetrics.csv")
    policies = _read(directory, "SpendingPolicyMetadata.csv")
    studio_daily = _read(directory, "StudioTenantDaily.csv")
    studio_agents = _read(directory, "StudioPerAgent.csv")
    studio_users = _read(directory, "StudioPerUser.csv")
    github = _read(directory, "GitHubAiUsage.csv")
    foundry = _read(directory, "AzureAiSpendDaily.csv")
    foundry_tokens = _read(directory, "AzureAiTokensDaily.csv")
    solution_spend = _read(directory, "AzureSolutionSpend.csv")
    deployment_health = _read(directory, "AzureDeploymentHealth.csv")
    people = _read(directory, "PeopleMetaData.csv")
    github_map = _read(directory, "GitHubUserMap.csv")
    rate_card = _read(directory, "LicenseRateCard.csv")

    policy_names = {row["SpendingPolicyId"]: row["Name"] for row in policies if row.get("SpendingPolicyId")}
    cowork_by_week: dict[str, list[dict[str, str]]] = defaultdict(list)
    cowork_by_service: dict[str, list[dict[str, str]]] = defaultdict(list)
    cowork_by_policy: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in cowork:
        cowork_by_week[_iso_date(row["MetricDate"])].append(row)
        cowork_by_service[row.get("ServiceName", "") or "(Not recorded)"].append(row)
        policy_id = row.get("SpendingPolicyId", "")
        label = "Outside policy" if policy_id == "00000000-0000-0000-0000-000000000000" else policy_names.get(policy_id, policy_id or "(Not recorded)")
        cowork_by_policy[label].append(row)

    cowork_weeks = [
        {"date": date, "credits": _decimal_text(_sum(rows, "Total Copilot Credits used")),
         "sessions": int(_sum(rows, "Session count")), "users": len({row.get("PersonId", "") for row in rows})}
        for date, rows in sorted(cowork_by_week.items())
    ]
    cowork_services = [
        {"name": name, "value": _decimal_text(_sum(rows, "Total Copilot Credits used"))}
        for name, rows in sorted(cowork_by_service.items(), key=lambda item: (-_sum(item[1], "Total Copilot Credits used"), item[0]))
    ]
    cowork_policies = [
        {"name": name, "value": _decimal_text(_sum(rows, "Total Copilot Credits used"))}
        for name, rows in sorted(cowork_by_policy.items(), key=lambda item: (-_sum(item[1], "Total Copilot Credits used"), item[0]))[:12]
    ]

    studio_by_day: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in studio_daily:
        studio_by_day[_iso_date(row["Usage Date"])].append(row)
    studio_days = [
        {"date": date,
         "prepaid": _decimal_text(_sum(rows, "Prepaid Consumed Quantity")),
         "payg": _decimal_text(_sum(rows, "Pay as you go Consumed Quantity"))}
        for date, rows in sorted(studio_by_day.items())
    ]
    studio_features: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for row in studio_agents:
        label = row.get("AI Feature/Billable Feature", "").strip() or "(Not recorded)"
        studio_features[label] += _number(row, "Billed credit") + _number(row, "Non-billed credit")
    studio_latest_date = max(studio_by_day, default="")
    studio_snapshot_month = studio_latest_date[:7] if studio_latest_date else None
    studio_total = _sum(studio_daily, "Prepaid Consumed Quantity") + _sum(studio_daily, "Pay as you go Consumed Quantity")
    studio_prepaid = _sum(studio_daily, "Prepaid Consumed Quantity")
    studio_payg = _sum(studio_daily, "Pay as you go Consumed Quantity")

    github_by_day: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in github:
        github_by_day[_iso_date(row["date"])].append(row)
    github_days = [
        {"date": date, "credits": _decimal_text(_sum(rows, "quantity")),
         "gross": _decimal_text(_sum(rows, "gross_amount")),
         "discount": _decimal_text(_sum(rows, "discount_amount")),
         "net": _decimal_text(_sum(rows, "net_amount"))}
        for date, rows in sorted(github_by_day.items())
    ]
    github_models = _group(github, "model", "quantity")
    github_orgs = _group(github, "organization", "quantity")
    github_users = {row.get("username", "").strip().lower() for row in github if row.get("username", "").strip()}
    github_currencies = sorted({row.get("currency", "").strip() for row in github if row.get("currency", "").strip()})

    foundry_by_day: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    foundry_by_meter: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in foundry:
        currency = row.get("Currency", "").strip() or "Not supplied"
        foundry_by_day[(currency, _iso_date(row["UsageDate"]))].append(row)
        foundry_by_meter[(currency, row.get("Meter", "").strip() or "(Not recorded)")].append(row)
    tokens_by_day: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for row in foundry_tokens:
        metric = row.get("Metric", "")
        if metric in ("InputTokens", "OutputTokens"):
            tokens_by_day[_iso_date(row["Date"])][metric] += _number(row, "Value")
    foundry_days = [
        {"date": date, "currency": currency, "cost": _decimal_text(_sum(rows, "Cost"))}
        for (currency, date), rows in sorted(foundry_by_day.items())
    ]
    foundry_token_days = [
        {"date": date,
         "inputTokens": _decimal_text(values["InputTokens"]),
         "outputTokens": _decimal_text(values["OutputTokens"])}
        for date, values in sorted(tokens_by_day.items())
    ]
    foundry_meters = [
        {"currency": currency, "name": meter, "value": _decimal_text(_sum(rows, "Cost"))}
        for (currency, meter), rows in sorted(foundry_by_meter.items(),
                                                key=lambda item: (item[0][0], -_sum(item[1], "Cost"), item[0][1]))[:24]
    ]
    foundry_currencies = sorted({row.get("Currency", "").strip() or "Not supplied" for row in foundry})
    foundry_costs = [
        {"currency": code, "cost": _decimal_text(_sum([row for row in foundry if (row.get("Currency", "").strip() or "Not supplied") == code], "Cost"))}
        for code in foundry_currencies
    ]
    latest_snapshot = max((row.get("SnapshotDate", "") for row in deployment_health), default="")
    latest_health = [row for row in deployment_health if row.get("SnapshotDate", "") == latest_snapshot]
    health = [
        {"deployment": row.get("DeploymentName") or row.get("DeploymentId") or "(Unnamed)",
         "model": row.get("ModelName", ""),
         "sku": row.get("SkuName", ""),
         "region": row.get("Region", ""),
         "utilization": row.get("MeanUtilizationPct", ""),
         "peakUtilization": row.get("PeakUtilizationPct", ""),
         "requests": row.get("Requests", ""),
         "errors": row.get("ServerErrors5xx", ""),
         "throttles": row.get("Throttles429", ""),
         "latencyMs": row.get("MeanLatencyMs", "")}
        for row in latest_health
    ]
    solution_currencies: dict[str, list[dict[str, str]]] = defaultdict(list)
    solution_by_day: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    solution_by_category: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    solution_by_application: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in solution_spend:
        currency = row.get("Currency", "").strip() or "Not supplied"
        solution_currencies[currency].append(row)
        date = _iso_date(row["UsageDate"])
        solution_by_day[(currency, date)].append(row)
        solution_by_category[(currency, row.get("ServiceCategory", "").strip() or "(Not recorded)")].append(row)
        solution_by_application[(currency, row.get("Application", "").strip() or "(Not tagged)")].append(row)
    solution_totals = [
        {"currency": currency,
         "actual": _decimal_text(_sum(rows, "ActualCost")),
         "amortized": _decimal_text(_sum(rows, "AmortizedCost")),
         "taggedCost": _decimal_text(_sum([row for row in rows if row.get("AllocationStatus") == "Tagged"], "ActualCost")),
         "rows": len(rows)}
        for currency, rows in sorted(solution_currencies.items())
    ]
    solution_days = [
        {"date": date, "currency": currency,
         "actual": _decimal_text(_sum(rows, "ActualCost")),
         "amortized": _decimal_text(_sum(rows, "AmortizedCost"))}
        for (currency, date), rows in sorted(solution_by_day.items())
    ]
    solution_categories = [
        {"currency": currency, "name": label, "value": _decimal_text(_sum(rows, "ActualCost"))}
        for (currency, label), rows in sorted(solution_by_category.items(),
                                                key=lambda item: (item[0][0], -_sum(item[1], "ActualCost"), item[0][1]))[:24]
    ]
    solution_applications = [
        {"currency": currency, "name": label, "value": _decimal_text(_sum(rows, "ActualCost"))}
        for (currency, label), rows in sorted(solution_by_application.items(),
                                                key=lambda item: (item[0][0], -_sum(item[1], "ActualCost"), item[0][1]))[:24]
    ]

    licenses = build_license_view(
        rate_card, people, cowork, github_map, github,
        sorted({date[:7] for date in [*cowork_by_week, *github_by_day]}), github_currencies)

    def coverage(name: str, rows: list[dict[str, str]], grain: str, dates: list[str] | None = None) -> dict:
        return {"source": name, "rows": len(rows), "grain": grain,
                "status": "Available" if rows else "No sample rows",
                "from": min(dates) if dates else None, "to": max(dates) if dates else None}

    source_coverage = [
        coverage("Cowork / Work IQ weekly credits", cowork, "person × service × policy × week", list(cowork_by_week)),
        coverage("Copilot Studio tenant usage", studio_daily, "environment × billing plan × capacity × day", list(studio_by_day)),
        coverage("Copilot Studio agent snapshot", studio_agents, "agent × feature × channel × environment; month-to-date", [studio_snapshot_month] if studio_snapshot_month else []),
        coverage("GitHub Copilot AI usage", github, "user × product × model × day", list(github_by_day)),
        coverage("Azure AI Foundry meter spend", foundry, "resource × meter × day", [date for _, date in foundry_by_day]),
        coverage("Azure AI Foundry token metrics", foundry_tokens, "resource × deployment × metric × day", list(tokens_by_day)),
        coverage("Azure AI solution spend", solution_spend, "resource × service × day", [row["date"] for row in solution_days]),
        coverage("Azure AI deployment health", latest_health, "latest snapshot × deployment", [latest_snapshot] if latest_snapshot else []),
        coverage("Seat assignments · Microsoft 365 Copilot", people, "person snapshot"),
        coverage("Seat assignments · GitHub Copilot", github_map, "username snapshot"),
        coverage("Licence rate card", rate_card, "product × plan × effective period"),
    ]
    return {
        "sample": True,
        "description": "Bundled synthetic Consumption Central sample. Separate native feeds; not live tenant data.",
        "coverage": source_coverage,
        "licenses": licenses,
        "cowork": {
            "credits": _decimal_text(_sum(cowork, "Total Copilot Credits used")),
            "users": len({row.get("PersonId", "") for row in cowork if row.get("PersonId", "")}),
            "sessions": int(_sum(cowork, "Session count")),
            "weeks": cowork_weeks, "services": cowork_services, "policies": cowork_policies,
        },
        "studio": {
            "credits": _decimal_text(studio_total), "prepaid": _decimal_text(studio_prepaid), "payg": _decimal_text(studio_payg),
            "paygShare": float(studio_payg / studio_total) if studio_total else 0,
            "days": studio_days, "features": [{"name": name, "value": _decimal_text(value)} for name, value in
                                                sorted(studio_features.items(), key=lambda item: (-item[1], item[0]))[:12]],
            "snapshotMonth": studio_snapshot_month,
            "snapshotAgents": len({row.get("Agent Id", "") for row in studio_agents if row.get("Agent Id", "")}),
            "snapshotCredits": _decimal_text(sum((_number(row, "Billed credit") + _number(row, "Non-billed credit") for row in studio_agents), ZERO)),
            "snapshotUsers": len({row.get("User Email", "").strip().lower() for row in studio_users if row.get("User Email", "").strip()}),
            "snapshotUserCredits": _decimal_text(_sum(studio_users, "Credits used")),
        },
        "github": {
            "credits": _decimal_text(_sum(github, "quantity")),
            "gross": _decimal_text(_sum(github, "gross_amount")),
            "discount": _decimal_text(_sum(github, "discount_amount")),
            "net": _decimal_text(_sum(github, "net_amount")),
            "users": len(github_users), "days": github_days, "models": github_models, "organizations": github_orgs,
            "currencies": github_currencies,
        },
        "foundry": {
            "cost": foundry_costs[0]["cost"] if len(foundry_costs) == 1 else None,
            "currency": foundry_currencies[0] if len(foundry_currencies) == 1 else "Multiple currencies" if foundry_currencies else "Not supplied",
            "costByCurrency": foundry_costs,
            "meterRows": len(foundry), "meters": foundry_meters, "days": foundry_days, "health": health,
            "tokenDays": foundry_token_days,
            "healthSnapshot": latest_snapshot or None,
            "inputTokens": _decimal_text(sum((values["InputTokens"] for values in tokens_by_day.values()), ZERO)),
            "outputTokens": _decimal_text(sum((values["OutputTokens"] for values in tokens_by_day.values()), ZERO)),
            "solutionTotals": solution_totals, "solutionDays": solution_days,
            "solutionCategories": solution_categories, "solutionApplications": solution_applications,
        },
    }
