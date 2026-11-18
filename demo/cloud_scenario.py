"""Invented multi-cloud scenario for the online demo: not provider billing data, prices or usage.

Every account, resource, tag and amount is made up. Region and service names are public product
names, used only so the charts read naturally. The same columns as a real cost export are filled,
including a reservation purchase with amortised usage and a credit, so every page has something
to show.
"""
import csv
import io
import json
from datetime import date, timedelta
from decimal import Decimal

ORIGIN = "Synthetic scenario; invented charges, not actual rates, invoices or production usage"
MONTH_START, MONTH_END = date(2026, 10, 1), date(2026, 11, 1)
DAYS = (MONTH_END - MONTH_START).days

ACCOUNTS = {
    "AWS": ("demo-aws-payer", "Northwind AWS", "Amazon Web Services (demo)"),
    "Microsoft": ("demo-azure-ea", "Northwind Azure", "Microsoft (demo)"),
    "Google Cloud": ("demo-gcp-billing", "Northwind Google Cloud", "Google (demo)"),
    "Oracle": ("demo-oci-tenancy", "Northwind OCI", "Oracle (demo)"),
}
# provider, sub-account, service, category, region id, region name, resource, SKU, unit,
# daily quantity, list unit price, contracted discount, tags (app, environment, business unit, cost centre)
RESOURCES = [
    ("AWS", "Retail web", "Amazon EC2", "Compute", "us-east-1", "US East (N. Virginia)", "web-fleet",
     "demo-ec2-m7g-large", "Hours", 96, "0.0816", "0.18", ("Storefront", "prod", "Retail", "CC-1001")),
    ("AWS", "Retail web", "Amazon CloudFront", "Networking", "global", "Global", "storefront-cdn",
     "demo-cf-egress", "GB", 2400, "0.0850", "0", None),
    ("AWS", "Data platform", "Amazon S3", "Storage", "us-east-1", "US East (N. Virginia)", "lake-raw",
     "demo-s3-standard", "GB-Months", 610, "0.0230", "0.05", ("Data lake", "prod", "Data", "CC-2001")),
    ("AWS", "Data platform", "Amazon RDS", "Databases", "eu-west-1", "Europe (Ireland)", "orders-db",
     "demo-rds-pg-r6g", "Hours", 48, "0.4800", "0.12", ("Orders", "prod", "Retail", "CC-1001")),
    ("AWS", "Data platform", "Amazon Bedrock", "AI and Machine Learning", "us-east-1",
     "US East (N. Virginia)", "support-assistant", "demo-bedrock-tokens", "1M tokens", 22, "6.0000", "0",
     ("Support assistant", "prod", "Customer operations", "CC-3001")),
    ("Microsoft", "Customer apps", "Virtual Machines", "Compute", "westeurope", "West Europe", "claims-api",
     "demo-vm-d4s-v5", "Hours", 72, "0.2300", "0.10", ("Claims", "prod", "Insurance", "CC-4001")),
    ("Microsoft", "Customer apps", "Azure SQL Database", "Databases", "westeurope", "West Europe",
     "claims-sql", "demo-sql-gp-8vcore", "Hours", 24, "1.6100", "0.15", ("Claims", "prod", "Insurance", "CC-4001")),
    ("Microsoft", "Analytics", "Storage", "Storage", "northeurope", "North Europe", "analytics-lake",
     "demo-adls-hot", "GB-Months", 820, "0.0208", "0.05", ("Analytics", "dev", "Data", "CC-2001")),
    ("Microsoft", "Analytics", "Azure OpenAI", "AI and Machine Learning", "swedencentral", "Sweden Central",
     "knowledge-search", "demo-aoai-tokens", "1M tokens", 18, "5.0000", "0",
     ("Knowledge search", "prod", "Engineering", "CC-5001")),
    ("Google Cloud", "ml-research", "Compute Engine", "Compute", "europe-west4", "Netherlands",
     "training-pool", "demo-gce-n2-standard-8", "Hours", 40, "0.3885", "0.20", ("Research", "dev", "Engineering", "CC-5001")),
    ("Google Cloud", "ml-research", "BigQuery", "Analytics", "eu", "EU multi-region", "events-warehouse",
     "demo-bq-analysis", "TiB", 3, "6.2500", "0", ("Analytics", "prod", "Data", "CC-2001")),
    ("Google Cloud", "ml-research", "Vertex AI", "AI and Machine Learning", "europe-west4", "Netherlands",
     "research-agent", "demo-vertex-tokens", "1M tokens", 9, "7.5000", "0", ("Research agent", "prod", "Product", "CC-6001")),
    ("Oracle", "Finance", "OCI Compute", "Compute", "uk-london-1", "UK South (London)", "ledger-app",
     "demo-oci-e5-flex", "OCPU Hours", 48, "0.0300", "0.25", ("Ledger", "prod", "Finance", "CC-7001")),
    ("Oracle", "Finance", "Autonomous Database", "Databases", "uk-london-1", "UK South (London)", "ledger-db",
     "demo-adb-ecpu", "ECPU Hours", 48, "0.3360", "0.25", ("Ledger", "prod", "Finance", "CC-7001")),
]
RESERVED = "claims-api"
RESERVATION_PRICE = Decimal("3720.00")
CREDIT = ("Google Cloud", "ml-research", 15, Decimal("-250.00"))


def _row(provider, sub_account, service, category, start, end, **values):
    account_id, account_name, issuer = ACCOUNTS[provider]
    row = {
        "ProviderName": provider, "PublisherName": issuer, "InvoiceIssuerName": issuer,
        "BillingAccountId": account_id, "BillingAccountName": account_name,
        "SubAccountId": f"demo-{sub_account.lower().replace(' ', '-')}", "SubAccountName": sub_account,
        "ServiceName": service, "ServiceCategory": category, "BillingCurrency": "USD",
        "BillingPeriodStart": str(MONTH_START), "BillingPeriodEnd": str(MONTH_END),
        "ChargePeriodStart": str(start), "ChargePeriodEnd": str(end),
        "ChargeCategory": "Usage", "ChargeClass": "", "ChargeFrequency": "Usage-Based", "ChargeDescription": "",
        "PricingCategory": "Standard", "RegionId": "", "RegionName": "", "ResourceId": "", "ResourceName": "",
        "ResourceType": "", "SkuId": "", "SkuPriceId": "", "ConsumedQuantity": "", "ConsumedUnit": "",
        "PricingQuantity": "", "PricingUnit": "", "ListUnitPrice": "", "ContractedUnitPrice": "",
        "ListCost": "", "ContractedCost": "", "BilledCost": "0", "EffectiveCost": "0",
        "CommitmentDiscountCategory": "", "CommitmentDiscountId": "", "CommitmentDiscountName": "",
        "CommitmentDiscountStatus": "", "CommitmentDiscountType": "", "Tags": "", "x_DataOrigin": ORIGIN,
    }
    row.update(values)
    return row


def scenario_rows():
    rows = []
    reservation_id = "demo-reservation-claims-api"
    daily_amortisation = (RESERVATION_PRICE / DAYS).quantize(Decimal("0.0001"))
    for index, (provider, sub_account, service, category, region_id, region, resource, sku, unit, base,
                list_price, discount, tags) in enumerate(RESOURCES):
        list_unit = Decimal(list_price)
        contracted_unit = (list_unit * (1 - Decimal(discount))).quantize(Decimal("0.0001"))
        ai = category == "AI and Machine Learning"
        for day in range(DAYS):
            start = MONTH_START + timedelta(days=day)
            weekend = start.weekday() >= 5 and category in ("Compute", "AI and Machine Learning")
            factor = 100 + (day * 7 + index * 13) % 30 + (day * 2 if ai else 0) - (25 if weekend else 0)
            quantity = (Decimal(base) * factor / 100).quantize(Decimal("0.01"))
            list_cost, contracted_cost = quantity * list_unit, quantity * contracted_unit
            values = {
                "RegionId": region_id, "RegionName": region, "ResourceName": resource,
                "ResourceId": f"demo/{provider.lower().replace(' ', '-')}/{resource}", "ResourceType": service,
                "SkuId": sku, "SkuPriceId": f"{sku}-list", "ConsumedQuantity": str(quantity), "ConsumedUnit": unit,
                "PricingQuantity": str(quantity), "PricingUnit": unit, "ListUnitPrice": str(list_unit),
                "ContractedUnitPrice": str(contracted_unit), "ListCost": str(list_cost),
                "ContractedCost": str(contracted_cost), "BilledCost": str(contracted_cost),
                "EffectiveCost": str(contracted_cost),
                "ChargeDescription": f"{service} usage for {resource} (invented)",
                "Tags": json.dumps(dict(zip(("application", "environment", "business_unit", "cost_center"), tags)))
                if tags else "",
            }
            if resource == RESERVED:
                values.update(
                    BilledCost="0", EffectiveCost=str(daily_amortisation), PricingCategory="Committed",
                    CommitmentDiscountCategory="Usage", CommitmentDiscountId=reservation_id,
                    CommitmentDiscountName="Claims API 1-year reservation (demo)",
                    CommitmentDiscountStatus="Used", CommitmentDiscountType="Reservation",
                )
            rows.append(_row(provider, sub_account, service, category, start, start + timedelta(days=1), **values))
    rows.append(_row(
        "Microsoft", "Customer apps", "Virtual Machines", "Compute", MONTH_START, MONTH_END,
        ChargeCategory="Purchase", ChargeFrequency="One-Time", PricingCategory="Committed",
        ChargeDescription="Reservation purchase, amortised across the month (invented)",
        BilledCost=str(RESERVATION_PRICE), EffectiveCost="0", ResourceId=reservation_id,
        CommitmentDiscountCategory="Usage", CommitmentDiscountId=reservation_id,
        CommitmentDiscountName="Claims API 1-year reservation (demo)", CommitmentDiscountType="Reservation",
    ))
    provider, sub_account, day, amount = CREDIT
    start = MONTH_START + timedelta(days=day)
    rows.append(_row(
        provider, sub_account, "Compute Engine", "Compute", start, start + timedelta(days=1),
        ChargeCategory="Credit", ChargeFrequency="One-Time", PricingCategory="",
        ChargeDescription="Promotional credit (invented)", BilledCost=str(amount), EffectiveCost=str(amount),
    ))
    return rows


def scenario_csv() -> str:
    rows = scenario_rows()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=rows[0])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
