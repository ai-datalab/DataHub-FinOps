"""Seat-licence cost estimates from a rate card and seat assignments, kept apart from credit and token usage."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

ZERO = Decimal(0)
BASES = {"Estimate", "Billed in FOCUS"}


def _text(value: Decimal) -> str:
    return format(value, "f")


def _amount(row: dict[str, str], column: str) -> Decimal:
    value = row.get(column, "").strip() or "0"
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid numeric value in {column}: {value!r}.") from error
    if not result.is_finite():
        raise ValueError(f"Non-finite numeric value in {column}: {value!r}.")
    return result


def _has_usage(row: dict[str, str], column: str) -> bool:
    return _amount(row, column) > 0


def _day(value: str, column: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as error:
        raise ValueError(f"{column} in LicenseRateCard.csv must be an ISO date, not {value!r}.") from error


def parse_rate_card(rows: list[dict[str, str]]) -> list[dict]:
    rates = []
    for row in rows:
        price = _amount(row, "UnitPrice")
        if price < 0:
            raise ValueError(f"UnitPrice in LicenseRateCard.csv must not be negative, not {row.get('UnitPrice')!r}.")
        currency = row.get("Currency", "").strip()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(f"Currency in LicenseRateCard.csv must be a three-letter code, not {currency!r}.")
        unit = row.get("Unit", "").strip() or "user/month"
        if unit != "user/month":
            raise ValueError(f"LicenseRateCard.csv supports only the user/month unit, not {unit!r}.")
        basis = row.get("Basis", "").strip() or "Estimate"
        if basis not in BASES:
            raise ValueError(f"Basis in LicenseRateCard.csv must be one of {sorted(BASES)}, not {basis!r}.")
        start = _day(row.get("EffectiveFrom", ""), "EffectiveFrom")
        end = row.get("EffectiveTo", "").strip()
        end = _day(end, "EffectiveTo") if end else ""
        if end and end < start:
            raise ValueError("EffectiveTo in LicenseRateCard.csv is earlier than EffectiveFrom.")
        rates.append({"product": row.get("Product", "").strip(), "plan": row.get("Plan", "").strip(),
                      "price": price, "currency": currency.upper(), "from": start, "to": end,
                      "basis": basis, "source": row.get("Source", "").strip()})
    return rates


def _rate_for(rates: list[dict], product: str, plan: str, month: str) -> dict | None:
    """Latest rate effective on the first day of the month; mid-month changes are not prorated."""
    first = f"{month}-01"
    effective = [rate for rate in rates if rate["product"] == product and rate["plan"] == plan
                 and rate["from"] <= first and (not rate["to"] or rate["to"] >= first)]
    return max(effective, key=lambda rate: rate["from"], default=None)


def _seat_groups(people, cowork, github_map, github) -> list[dict]:
    groups = []
    if people:
        licensed = {row["PeopleHistoricalId"] for row in people
                    if row.get("PeopleHistoricalId") and row.get("IsCopilotLicensed", "").strip().lower() == "true"}
        active = {row["PeopleHistoricalId"] for row in cowork
                  if row.get("PeopleHistoricalId") and _has_usage(row, "Total Copilot Credits used")}
        # Cowork credits meter one capability, so absence of credits does not show a seat is unused.
        groups.append({"product": "Microsoft 365 Copilot", "plan": "Microsoft 365 Copilot", "seats": licensed,
                       "active": licensed & active, "withoutSeat": len(active - licensed),
                       "usageSignal": "Cowork / Work IQ credits", "signalComplete": False})
    if github_map:
        plan_of = {row["username"].strip().lower(): row.get("plan", "").strip() or "(No plan)"
                   for row in github_map if row.get("username", "").strip()}
        active = {row["username"].strip().lower() for row in github
                  if row.get("username", "").strip() and _has_usage(row, "quantity")}
        by_plan: dict[str, set[str]] = defaultdict(set)
        for user, plan in plan_of.items():
            by_plan[plan].add(user)
        for plan, users in sorted(by_plan.items()):
            groups.append({"product": "GitHub Copilot", "plan": plan, "seats": users, "active": users & active,
                           "withoutSeat": len(active - plan_of.keys()), "usageSignal": "GitHub AI credits",
                           "signalComplete": True})
    return groups


def build_license_view(rate_rows: list[dict[str, str]], people: list[dict[str, str]], cowork: list[dict[str, str]],
                       github_map: list[dict[str, str]], github: list[dict[str, str]], months: list[str],
                       github_currencies: list[str]) -> dict:
    """Join seat assignments to usage activity, then price seats by month from the rate card."""
    rates = parse_rate_card(rate_rows)
    groups = _seat_groups(people, cowork, github_map, github)
    plans, monthly = [], []
    totals: dict[str, dict] = {}
    for group in groups:
        seats, active, complete = len(group["seats"]), len(group["active"]), group["signalComplete"]
        found = [(month, rate) for month in months if (rate := _rate_for(rates, group["product"], group["plan"], month))]
        if len({rate["currency"] for _, rate in found}) > 1:
            raise ValueError(f"The {group['plan']} rate changes currency within the sample window; split it into separate plans.")
        row = {"product": group["product"], "plan": group["plan"], "seats": seats, "seatsWithUsage": active,
               "seatsWithoutUsage": seats - active if complete else None, "usageSignal": group["usageSignal"],
               "usageSignalComplete": complete, "status": "No rate in rate card", "currency": None, "monthlyRate": None, "basis": None, "source": "",
               "windowCost": None, "noUsageCost": None, "unpricedMonths": len(months) - len(found)}
        if found:
            latest = found[-1][1]
            row.update(currency=latest["currency"], monthlyRate=_text(latest["price"]), basis=latest["basis"],
                       source=latest["source"], status=latest["basis"])
            estimated = [(month, rate) for month, rate in found if rate["basis"] == "Estimate"]
            if estimated:
                window = sum((rate["price"] * seats for _, rate in estimated), ZERO)
                idle = sum((rate["price"] * (seats - active) for _, rate in estimated), ZERO)
                row.update(windowCost=_text(window), noUsageCost=_text(idle) if complete else None)
                total = totals.setdefault(latest["currency"], {
                    "currency": latest["currency"], "windowCost": ZERO, "monthlyRunRate": ZERO, "seats": 0,
                    "reviewSeats": 0, "noUsageSeats": 0, "noUsageCost": ZERO})
                total["windowCost"] += window
                total["seats"] += seats
                if complete:
                    total["reviewSeats"] += seats
                    total["noUsageSeats"] += seats - active
                    total["noUsageCost"] += idle
                if estimated[-1][0] == months[-1]:
                    total["monthlyRunRate"] += estimated[-1][1]["price"] * seats
                monthly.extend({"month": month, "product": group["product"], "plan": group["plan"],
                                "currency": rate["currency"], "cost": _text(rate["price"] * seats)}
                               for month, rate in estimated)
        plans.append(row)

    github_months: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for row in github:
        month = row.get("date", "")[:7]
        for key, column in (("gross", "gross_amount"), ("discount", "discount_amount"), ("net", "net_amount")):
            github_months[month][key] += _amount(row, column)
    github_seat_currencies = {row["currency"] for row in plans
                              if row["product"] == "GitHub Copilot" and row["status"] == "Estimate"}
    return {
        "available": bool(plans),
        "months": months,
        "assumption": "Seat counts are the single assignment snapshot in the sample, applied to every month with usage. "
                      "Rates come from the rate card on the first day of each month and are not prorated.",
        "rates": [{**rate, "price": _text(rate["price"])} for rate in rates],
        "plans": plans,
        "withoutSeat": list({group["product"]: {"product": group["product"], "users": group["withoutSeat"],
                                                 "signal": group["usageSignal"]} for group in groups}.values()),
        "totals": [{key: _text(value) if isinstance(value, Decimal) else value for key, value in total.items()}
                   for _, total in sorted(totals.items())],
        "monthly": monthly,
        "githubUsage": [{"month": month, **{key: _text(value) for key, value in values.items()}}
                        for month, values in sorted(github_months.items())],
        "githubUsageComparable": bool(github) and len(github_currencies) == 1
        and github_seat_currencies == set(github_currencies),
        "githubUsageCurrencies": github_currencies,
    }
