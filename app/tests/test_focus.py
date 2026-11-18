from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import threading
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from focus_core import FIELDS, ImportFailure, dashboard, parse_files
from fabric_loader import TABLE, read_snapshot, write_snapshot
from server import FocusServer, SAMPLE, sample_dataset


def record(**overrides):
    return {
        "ProviderName": "Azure", "BilledCost": "1.25", "EffectiveCost": "1.00",
        "BillingCurrency": "USD", "BillingAccountId": "example-billing",
        "ServiceName": "Compute", "SubAccountName": "Engineering",
        "BillingPeriodStart": "2024-09-01", "BillingPeriodEnd": "2024-10-01",
        "ChargePeriodStart": "2024-09-01T00:00:00Z", "ChargePeriodEnd": "2024-09-02T00:00:00Z",
        **overrides,
    }


def file(rows=None, name="cost.csv"):
    rows = rows if rows is not None else [record()]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=rows[0])
    writer.writeheader()
    writer.writerows(rows)
    return {"name": name, "content": output.getvalue()}


def test_official_sample_unchanged_and_totals_match_independent_decimal_sum():
    assert hashlib.sha256(SAMPLE.read_bytes()).hexdigest() == "e91e5ac7edf01ed2c9d926f37ef7dc1ae2aae97956fea8da6c9ee488b1c2839e"
    original = list(csv.DictReader(io.StringIO(SAMPLE.read_text(encoding="utf-8"))))
    dataset = sample_dataset("cloud")
    result = dashboard(dataset, {})
    assert result["totalRows"] == len(original) == 1000
    assert {row["name"] for row in result["providers"]} == {"AWS", "Microsoft", "Oracle"}
    for source, output in (("BilledCost", "billed"), ("EffectiveCost", "effective")):
        assert Decimal(result[output]) == sum(Decimal(row[source]) for row in original)
    assert result["billed"] == "20.52022672899"
    assert len(dataset["rows"]) == 1000


def test_official_focus_pricing_quantity_resource_commitment_and_tags_are_typed():
    original = list(csv.DictReader(io.StringIO(SAMPLE.read_text(encoding="utf-8"))))
    dataset = sample_dataset("cloud")
    result = dashboard(dataset, {})
    assert all(isinstance(row["ListCost"], Decimal) for row in dataset["rows"])
    assert all(row["ContractedCost"] is None or isinstance(row["ContractedCost"], Decimal) for row in dataset["rows"])
    assert all(row["ConsumedQuantity"] is None or isinstance(row["ConsumedQuantity"], Decimal) for row in dataset["rows"])
    assert sum(row["ListCost"] is not None for row in dataset["rows"]) == 1000
    assert sum(row["ContractedCost"] is not None for row in dataset["rows"]) == 993
    assert sum(row["ConsumedQuantity"] is not None for row in dataset["rows"]) == 999
    assert sum(bool(row["ResourceId"]) for row in dataset["rows"]) == 925
    assert sum(bool(row["Tags"]) for row in dataset["rows"]) == 711
    assert sum(bool(row["CommitmentDiscountId"]) for row in dataset["rows"]) == 4
    assert result["coverage"][0]["listCostRows"] + result["coverage"][1]["listCostRows"] + result["coverage"][2]["listCostRows"] == 1000
    assert Decimal(result["providers"][0]["listCost"]) == sum(
        Decimal(row["ListCost"]) for row in original if row["ProviderName"] == result["providers"][0]["name"]
    )
    tagged = next(row for row in dataset["rows"] if row["TagApplication"])
    assert json.loads(tagged["Tags"])["application"] == tagged["TagApplication"]
    assert result["dimensionGroups"]


def test_dimension_filter_is_linked_and_quantity_sums_require_one_unit():
    dataset = sample_dataset("cloud")
    all_data = dashboard(dataset, {"dimension": "Region"})
    assert all_data["options"]["dimensionValue"]
    value = all_data["options"]["dimensionValue"][0]
    filtered = dashboard(dataset, {"dimension": "Region", "dimensionValue": value})
    expected = [row for row in dataset["rows"] if (row["RegionName"] or row["RegionId"]) == value]
    assert filtered["rows"] == len(expected)
    assert Decimal(filtered["billed"]) == sum(row["BilledCost"] for row in expected)
    assert filtered["dimensionGroups"][0]["name"] == value

    mixed = parse_files([file([
        record(ServiceName="Mixed service", ConsumedQuantity="2", ConsumedUnit="Requests"),
        record(ServiceName="Mixed service", ConsumedQuantity="3", ConsumedUnit="Hours"),
    ])], "test")
    group = dashboard(mixed, {})["services"][0]
    assert group["consumedQuantity"] is None and group["consumedUnit"] is None

    different_regions = parse_files([file([
        record(ProviderName="Azure", RegionName="east"),
        record(ProviderName="AWS", RegionName="west"),
    ])], "test")
    no_overlap = dashboard(different_regions, {
        "provider": "Azure", "dimension": "Region", "dimensionValue": "west",
    })
    assert no_overlap["rows"] == 0 and no_overlap["billed"] == "0"


def test_dimension_suggestions_are_bounded_but_exact_filter_accepts_other_values():
    rows = [record(ResourceId=f"resource-{index:03d}") for index in range(105)]
    dataset = parse_files([file(rows)], "test")
    overview = dashboard(dataset, {"dimension": "Resource"})
    assert len(overview["options"]["dimensionValue"]) == 100
    assert overview["dimensionValueCount"] == 105
    selected = dashboard(dataset, {"dimension": "Resource", "dimensionValue": "Azure / resource-104"})
    assert selected["rows"] == 1
    assert selected["resources"][0]["name"] == "Azure / resource-104"


def test_optional_focus_decimals_and_tags_reject_invalid_values():
    parsed = parse_files([file([record(ListCost="", ConsumedQuantity="", Tags="")])], "test")
    assert parsed["rows"][0]["ListCost"] is None
    assert parsed["rows"][0]["ConsumedQuantity"] is None
    for changes, message in (
        ({"ListUnitPrice": "NaN"}, "finite decimal"),
        ({"PricingQuantity": "1e25"}, "precision"),
        ({"Tags": "[]"}, "JSON object"),
        ({"Tags": '{"application": 3}'}, "string values"),
        ({"Tags": '{"CostCenter": "1", "CostCentre": "2"}'}, "conflicting values"),
    ):
        with pytest.raises(ImportFailure, match=message):
            parse_files([file([record(**changes)])], "test")


def test_list_vs_contracted_cost_uses_the_same_eligible_rows():
    dataset = parse_files([file([
        record(ListCost="10", ContractedCost="8"),
        record(ListCost="20", ContractedCost=""),
        record(ListCost="", ContractedCost="5"),
    ])], "test")
    (provider,) = dashboard(dataset, {})["providers"]
    assert provider["listCost"] == "30"
    assert provider["contractedCost"] == "13"
    assert provider["comparisonRows"] == 1
    assert provider["comparisonListCost"] == "10"
    assert provider["comparisonContractedCost"] == "8"
    assert provider["comparisonBilledCost"] == "1.25"


def test_unit_price_comparison_matches_sku_price_and_pricing_unit():
    dataset = parse_files([file([
        record(SkuPriceId="sku-a", PricingUnit="Hours", ListUnitPrice="10", ContractedUnitPrice="8"),
        record(SkuPriceId="sku-a", PricingUnit="Hours", ListUnitPrice="10", ContractedUnitPrice="8"),
        record(SkuPriceId="sku-a", PricingUnit="Hours", ListUnitPrice="10", ContractedUnitPrice=""),
        record(SkuPriceId="sku-b", PricingUnit="Requests", ListUnitPrice="10", ContractedUnitPrice="8"),
    ])], "test")
    comparison = next(item for item in dashboard(dataset, {})["unitPriceComparisons"] if item["name"] == "Azure / sku-a")
    assert comparison == {
        "name": "Azure / sku-a", "unit": "Hours", "rows": 2,
        "listUnitPrice": "10", "contractedUnitPrice": "8",
    }


def test_current_headers_bom_multiline_and_unknown_columns_preserved():
    row = record(ServiceName='Compute, "on demand"\nVMs', x_Custom="private-note")
    row["ServiceProviderName"] = row.pop("ProviderName")
    upload = file([row])
    upload["content"] = "\ufeff" + upload["content"]
    result = parse_files([upload], "source")
    parsed = result["rows"][0]
    assert parsed["Provider"] == "Azure"
    assert parsed["ServiceName"] == row["ServiceName"]
    assert json.loads(parsed["RawRecord"])["x_Custom"] == "private-note"


def test_negative_values_decimals_duplicates_and_currency_are_not_lost():
    result = parse_files([file([
        record(BilledCost="0.1"), record(BilledCost="0.2"), record(BilledCost="-0.05"),
        record(BilledCost="0.1"), record(BillingCurrency="EUR", BilledCost="100"),
    ])], "test")
    usd = dashboard(result, {"currency": "USD"})
    assert Decimal(usd["billed"]) == Decimal("0.35")
    assert usd["rows"] == 4
    assert Decimal(usd["credits"]) == Decimal("-0.05")
    assert Decimal(dashboard(result, {"currency": "EUR"})["billed"]) == Decimal("100")


@pytest.mark.parametrize("changes,expected", [
    ({"BilledCost": "NaN"}, "finite decimal"), ({"EffectiveCost": "Infinity"}, "finite decimal"),
    ({"BilledCost": "1e25"}, "precision"), ({"BilledCost": "0.0000000000000000001"}, "precision"),
    ({"BilledCost": "1e999999999"}, "precision"), ({"BilledCost": "1e-999999999"}, "precision"),
    ({"BillingCurrency": ""}, "empty"), ({"BillingCurrency": "usd"}, "uppercase"),
    ({"BillingAccountId": ""}, "empty"), ({"ProviderName": ""}, "provider"),
    ({"ChargePeriodStart": "2024-02-31"}, "ISO"), ({"ChargePeriodEnd": "2024-08-31"}, "after"),
])
def test_invalid_snapshot_rejected(changes, expected):
    with pytest.raises(ImportFailure, match=expected):
        parse_files([file([record(), record(**changes)])], "test")


def test_partition_files_combined_but_identical_files_rejected():
    parts = [file(name="part1.csv"), file([record(BilledCost="2")], "part2.csv")]
    assert len(parse_files(parts, "test")["rows"]) == 2
    with pytest.raises(ImportFailure, match="identical file"):
        parse_files([file(name="a.csv"), file(name="b.csv")], "test")


def test_decimal_boundary_and_trailing_zeroes_preserved_exactly():
    value = "99999999999999999999.999999999999999999"
    dataset = parse_files([file([record(BilledCost=value), record(BilledCost="0.1000000000000000000")])], "test")
    assert dataset["rows"][0]["BilledCost"] == Decimal(value)
    assert dashboard(dataset, {})["billed"] == "100000000000000000000.0999999999999999990"


def test_duplicate_headers_missing_columns_and_broken_csv_rejected():
    for content, message in [
        ("BilledCost,BilledCost\n1,2", "duplicate column"),
        ("BilledCost\n1", "missing required"),
        (file()["content"].replace("1.25", '"unfinished'), "invalid CSV"),
        (file()["content"].splitlines()[0] + "\n", "no data"),
        (file()["content"] + "too,few\n", "different number"),
    ]:
        with pytest.raises(ImportFailure, match=message):
            parse_files([{"name": "bad.csv", "content": content}], "test")


def test_timezone_and_filter_empty_state():
    dataset = parse_files([file([
        record(ChargePeriodStart="2024-09-01T01:00:00+02:00", ServiceName="A"),
        record(ProviderName="AWS", ServiceName="B"),
    ])], "test")
    assert dataset["rows"][0]["ChargePeriodStart"] == "2024-08-31 23:00:00"
    result = dashboard(dataset, {"provider": "AWS", "service": "A"})
    assert result["billed"] == "0" and result["rows"] == 0
    with pytest.raises(ValueError, match="Unknown"):
        dashboard(dataset, {"currency": "GBP"})


def test_limits_and_source_identifiers(monkeypatch):
    import focus_core
    with pytest.raises(ImportFailure, match="Source ID"):
        parse_files([file()], "bad' OR 1=1")
    monkeypatch.setattr(focus_core, "MAX_ROWS", 1)
    with pytest.raises(ImportFailure, match="rows"):
        parse_files([file([record(), record()])], "test")
    monkeypatch.setattr(focus_core, "MAX_BYTES", 1)
    with pytest.raises(ImportFailure, match="20 MiB"):
        parse_files([file()], "test")


def test_fabric_folder_uses_same_parser_and_rejects_non_csv(tmp_path):
    part = file([record(), record(BilledCost="-0.5")])
    (tmp_path / "part.csv").write_text(part["content"], encoding="utf-8")
    result = read_snapshot(tmp_path, "azure")
    assert dashboard(result, {})["billed"] == "0.75"
    (tmp_path / "old.json").write_text("{}")
    with pytest.raises(ImportFailure, match="only CSV"):
        read_snapshot(tmp_path, "azure")


@pytest.fixture
def local_server():
    server = FocusServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def fetch(base, path, payload=None, headers=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(base + path, data=body, headers=headers or
                      ({"Content-Type": "application/json", "Origin": base} if body else {}))
    return urlopen(request, timeout=5)


def test_http_import_replaces_and_bad_import_preserves_last_good(local_server):
    base = local_server
    data = {"files": [file([record(BilledCost="7")])], "sourceId": "upload"}
    with fetch(base, "/api/import", data) as response:
        payload = json.load(response)
        assert payload["billed"] == "7"
        assert payload["nativeConsumption"]["sample"] is True
        assert payload["nativeConsumption"]["cowork"]["users"] > 0
    with fetch(base, "/api/import", data) as response:
        assert json.load(response)["rows"] == 1
    with pytest.raises(HTTPError) as error:
        fetch(base, "/api/import", {"files": [file([record(BilledCost="NaN")])]})
    assert error.value.code == 400
    with fetch(base, "/api/dashboard") as response:
        assert json.load(response)["billed"] == "7"
    with fetch(base, "/api/sample", {"kind": "cloud"}) as response:
        assert json.load(response)["totalRows"] == 1000


def test_exporter_cli_to_http_dashboard_preserves_unpriced_usage(local_server, tmp_path):
    from exporter_adapter import main as convert_export

    sample = Path(__file__).parents[2] / "samples" / "focus-exporter" / "sample.json"
    costs = tmp_path / "costs.csv"
    unpriced = tmp_path / "unpriced.json"
    assert convert_export([
        str(sample), "--output", str(costs), "--unpriced-output", str(unpriced),
    ]) == 0

    data = {"files": [{"name": costs.name, "content": costs.read_text(encoding="utf-8")}],
            "sourceId": "exporter-test"}
    with fetch(local_server, "/api/import", data) as response:
        payload = json.load(response)
        assert payload["totalRows"] == 4
        assert Decimal(payload["billed"]) == Decimal("0.037")
        assert Decimal(payload["effective"]) == Decimal("0.037")

    with fetch(local_server, "/api/dashboard?provider=Anthropic") as response:
        payload = json.load(response)
        assert payload["rows"] == 2
        assert Decimal(payload["billed"]) == Decimal("0.007")
    with fetch(local_server, "/api/dashboard?provider=OpenAI") as response:
        payload = json.load(response)
        assert payload["rows"] == 2
        assert Decimal(payload["billed"]) == Decimal("0.030")

    missing_cost = json.loads(unpriced.read_text(encoding="utf-8"))
    assert missing_cost == [json.loads(sample.read_text(encoding="utf-8"))[-1]]
    assert missing_cost[0]["ConsumedQuantity"] == "300"
    assert missing_cost[0]["BilledCost"] == ""


def test_http_boundaries_and_static_allowlist(local_server):
    for path, headers in [
        ("/api/dashboard", {"Host": "attacker.example.com"}),
        ("/api/import", {"Content-Type": "application/json", "Origin": "https://attacker.example.com"}),
    ]:
        with pytest.raises(HTTPError) as error:
            fetch(local_server, path, {} if "import" in path else None, headers)
        assert error.value.code == 403
    with pytest.raises(HTTPError) as error:
        fetch(local_server, "/../../server.py")
    assert error.value.code == 404
    with fetch(local_server, "/") as response:
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
        assert b"Import cloud cost CSV" in response.read()
    for path in ("/dashboard.js", "/charts.js", "/dashboard.css"):
        with fetch(local_server, path) as response:
            assert response.status == 200


def test_fabric_write_contract_targets_only_source_partition(monkeypatch):
    """Check orchestration without claiming a local Spark/Delta integration test."""
    from types import ModuleType, SimpleNamespace

    types = ModuleType("pyspark.sql.types")
    types.DecimalType = lambda precision, scale: ("decimal", precision, scale)
    types.StringType = lambda: "string"
    types.IntegerType = lambda: "int"
    types.LongType = lambda: "long"
    types.StructField = lambda name, dataType, nullable: SimpleNamespace(name=name, dataType=dataType)
    types.StructType = list
    monkeypatch.setitem(sys.modules, "pyspark", ModuleType("pyspark"))
    monkeypatch.setitem(sys.modules, "pyspark.sql", ModuleType("pyspark.sql"))
    monkeypatch.setitem(sys.modules, "pyspark.sql.types", types)
    calls = []

    class Writer:
        def __getattr__(self, name):
            def operation(*args):
                calls.append((name, args))
                return self
            return operation

    class Spark:
        catalog = SimpleNamespace(tableExists=lambda name: True)
        def createDataFrame(self, rows, schema):
            self.schema = schema
            assert isinstance(rows[0]["BilledCost"], Decimal)
            return SimpleNamespace(write=Writer())
        def table(self, name):
            assert name == TABLE
            return SimpleNamespace(schema=self.schema)
        def sql(self, statement):
            assert statement == f"DESCRIBE DETAIL {TABLE}"
            return SimpleNamespace(first=lambda: {"format": "delta", "partitionColumns": ["SourceId"]})

    spark = Spark()
    dataset = parse_files([file()], "azure")
    assert write_snapshot(spark, dataset) == 1
    assert ("mode", ("overwrite",)) in calls
    assert ("option", ("replaceWhere", "SourceId = 'azure'")) in calls
    assert calls[-1] == ("saveAsTable", (TABLE,))
    spark.table = lambda name: SimpleNamespace(schema=[])
    with pytest.raises(ValueError, match="incompatible schema"):
        write_snapshot(spark, dataset)


def test_ai_scenario_has_claude_openai_model_workload_and_token_totals():
    dataset = sample_dataset("ai")
    result = dashboard(dataset, {})
    assert result["sampleKind"] == "ai"
    assert {row["name"] for row in result["providers"]} == {"Anthropic", "OpenAI", "Microsoft"}
    assert len(result["models"]) == 5
    assert result["tokenRows"] == result["rows"] == 155
    claude = dashboard(dataset, {"provider": "Anthropic", "model": "Claude Sonnet"})
    assert claude["rows"] == 31
    assert len(claude["models"]) == 1
    original = [row for row in dataset["rows"] if row["Model"] == "Claude Sonnet"]
    assert Decimal(claude["billed"]) == sum(row["BilledCost"] for row in original)
    assert int(claude["tokens"]["CachedInputTokens"]) == sum(row["CachedInputTokens"] for row in original)
    assert len(dashboard(dataset, {"workload": "Support assistant"})["models"]) == 2


def test_missing_tokens_are_not_zero_and_invalid_tokens_reject_snapshot():
    plain = parse_files([file()], "test")
    assert dashboard(plain, {})["tokens"]["InputTokens"] is None
    explicit = parse_files([file([record(x_InputTokens="0")])], "test")
    assert dashboard(explicit, {})["tokens"]["InputTokens"] == "0"
    for value in ("-1", "1.5", "NaN", "1000000000000000"):
        with pytest.raises(ImportFailure, match="nonnegative integer"):
            parse_files([file([record(x_InputTokens=value)])], "test")


def test_chart_series_sum_back_to_the_total_and_heat_follows_the_labels():
    ai = dashboard(sample_dataset("ai"), {})
    total = Decimal(ai["billed"])
    assert sum(Decimal(row["billed"]) for row in ai["trendProvider"]) == total
    assert sum(Decimal(row["billed"]) for row in ai["trendModel"]) == total
    assert ai["heat"]["kind"] == "workload-model"
    assert ai["heat"]["rowsUsed"] <= ai["heat"]["rowsTotal"] == ai["rows"]
    assert len(ai["coverage"]) == 3 and all(item["tokenRows"] == item["rows"] for item in ai["coverage"])

    cloud = dashboard(sample_dataset("cloud"), {})
    assert cloud["options"]["model"] == [] and cloud["tokenRows"] == 0
    assert cloud["heat"]["kind"] == "service-provider"
    assert all(item["modelRows"] == 0 and item["tokenRows"] == 0 for item in cloud["coverage"])


def test_cost_per_million_tokens_uses_only_token_complete_rows():
    complete = record(x_Model="m", x_InputTokens="400000", x_OutputTokens="100000",
                      x_CachedInputTokens="400000", x_CacheWriteTokens="100000", BilledCost="2.00")
    partial = record(x_Model="m", ServiceName="Other", x_InputTokens="1", BilledCost="50.00")
    result = dashboard(parse_files([file([complete, partial])], "test"), {})
    cover = result["models"][0]["cover"]
    assert cover["rows"] == 1 and Decimal(cover["billed"]) == Decimal("2.00")
    assert cover["tokens"] == "1000000" and Decimal(cover["perMillion"]) == Decimal("2")


def charge_days(days, **overrides):
    return parse_files([file([record(ChargePeriodStart=f"2024-09-{day:02d}T00:00:00Z",
                                     ChargePeriodEnd=f"2024-09-{day:02d}T23:59:59Z", BilledCost="1.00", **overrides)
                              for day in days])], "test")


def test_run_rate_projects_partial_months_only():
    (partial,) = dashboard(charge_days(range(1, 11)), {})["runRate"]["providers"]
    assert partial["elapsed"] == 10 and partial["days"] == 30
    assert Decimal(partial["projected"]) == Decimal(30)
    (complete,) = dashboard(charge_days(range(1, 31)), {})["runRate"]["providers"]
    assert complete["elapsed"] == complete["days"] == 30 and complete["projected"] is None
    assert all(item["projected"] is None for item in dashboard(sample_dataset("ai"), {})["runRate"]["providers"])


def test_run_rate_does_not_project_charges_dated_outside_the_billing_period():
    early = parse_files([file([record(BillingPeriodStart="2024-10-01", BillingPeriodEnd="2024-11-01",
                                      ChargePeriodStart="2024-09-30T00:00:00Z",
                                      ChargePeriodEnd="2024-10-01T00:00:00Z")])], "test")
    (item,) = dashboard(early, {})["runRate"]["providers"]
    assert item["through"] is None and item["elapsed"] == 0 and item["projected"] is None
    assert Decimal(item["spent"]) == Decimal("1.25")
