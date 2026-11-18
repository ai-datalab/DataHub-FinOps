import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from exporter_adapter import convert_exporter_records, load_exporter_records, main
from focus_core import ImportFailure, parse_files


SAMPLE = Path(__file__).parents[2] / "samples" / "focus-exporter" / "sample.json"


def test_synthetic_exporter_sample_converts_and_imports():
    result = convert_exporter_records(load_exporter_records(SAMPLE))

    assert result.cost_csv is not None
    dataset = parse_files([{"name": "converted.csv", "content": result.cost_csv}], "test")
    rows = dataset["rows"]
    assert len(rows) == 4
    assert {row["Provider"] for row in rows} == {"OpenAI", "Anthropic"}
    assert sum(row["BilledCost"] for row in rows) == Decimal("0.037")

    by_bucket = {(row["Provider"], json.loads(row["RawRecord"])["SkuMeter"]): row for row in rows}
    assert by_bucket[("OpenAI", "input")]["Model"] == "gpt-4o"
    assert by_bucket[("OpenAI", "input")]["InputTokens"] == 1000
    assert by_bucket[("OpenAI", "output")]["OutputTokens"] == 500
    assert by_bucket[("Anthropic", "cache_read")]["CachedInputTokens"] == 600
    assert by_bucket[("Anthropic", "cache_creation")]["CacheWriteTokens"] == 200
    assert all(row["InputTokens"] is None for row in rows
               if json.loads(row["RawRecord"])["SkuMeter"] != "input")


def test_unpriced_records_are_preserved_without_zero_cost():
    records = load_exporter_records(SAMPLE)
    result = convert_exporter_records(records)

    assert result.unpriced_records == [records[-1]]
    assert all(record["BilledCost"] == "" for record in result.unpriced_records)
    assert "priority" in json.dumps(result.unpriced_records)


def test_provider_aliases_must_not_conflict():
    records = load_exporter_records(SAMPLE)
    records[0]["ProviderName"] = "Different provider"

    with pytest.raises(ValueError, match="must identify one provider"):
        convert_exporter_records(records)


def test_recognised_token_bucket_requires_token_unit():
    records = load_exporter_records(SAMPLE)[:1]
    records[0]["ConsumedUnit"] = "requests"

    with pytest.raises(ValueError, match="ConsumedUnit=tokens"):
        convert_exporter_records(records)


def test_unknown_provider_token_type_is_not_inferred_from_meter():
    records = load_exporter_records(SAMPLE)[:1]
    records[0]["x_TokenType"] = "provider_specific_bucket"

    with pytest.raises(ValueError, match="x_TokenType is not a recognised token bucket"):
        convert_exporter_records(records)


def test_model_suffix_in_sku_meter_is_supported():
    records = load_exporter_records(SAMPLE)[:1]
    records[0]["SkuId"] = "gpt-4o-input"
    records[0]["SkuMeter"] = "gpt-4o-input"

    result = convert_exporter_records(records)
    row = parse_files([{"name": "converted.csv", "content": result.cost_csv}], "test")["rows"][0]

    assert row["Model"] == "gpt-4o"
    assert row["InputTokens"] == 1000


def test_csv_sink_output_can_be_normalised_again(tmp_path):
    first = convert_exporter_records(load_exporter_records(SAMPLE))
    source = tmp_path / "export.csv"
    source.write_text(first.cost_csv, encoding="utf-8")

    second = convert_exporter_records(load_exporter_records(source))

    assert second.cost_csv is not None
    assert len(parse_files([{"name": "roundtrip.csv", "content": second.cost_csv}], "test")["rows"]) == 4


def test_cli_requires_sidecar_before_writing_when_costless_records_exist(tmp_path, capsys):
    output = tmp_path / "costs.csv"

    result = main([str(SAMPLE), "--output", str(output)])

    assert result == 2
    assert not output.exists()
    assert "--unpriced-output" in capsys.readouterr().err


def test_unpriced_only_sample_produces_no_import_csv():
    records = load_exporter_records(SAMPLE)[-1:]

    result = convert_exporter_records(records)

    assert result.cost_csv is None
    assert len(result.unpriced_records) == 1


def test_csv_loader_rejects_duplicate_headers(tmp_path):
    source = tmp_path / "duplicate.csv"
    source.write_text("Provider,Provider\nOpenAI,OpenAI\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate column headers"):
        load_exporter_records(source)
