"""Convert focus-exporter's JSON or CSV output to the local prototype's import CSV."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from focus_core import MAX_BYTES, MAX_ROWS, ImportFailure, parse_files


TOKEN_FIELDS = {
    "input": "x_InputTokens",
    "input_tokens": "x_InputTokens",
    "uncached_input_tokens": "x_InputTokens",
    "output": "x_OutputTokens",
    "output_tokens": "x_OutputTokens",
    "cache_read": "x_CachedInputTokens",
    "cached_input": "x_CachedInputTokens",
    "cache_read_input_tokens": "x_CachedInputTokens",
    "cache_creation": "x_CacheWriteTokens",
    "cache_write": "x_CacheWriteTokens",
    "cache_creation.ephemeral_1h_input_tokens": "x_CacheWriteTokens",
    "cache_creation.ephemeral_5m_input_tokens": "x_CacheWriteTokens",
    "cache_creation_ephemeral_1h_input_tokens": "x_CacheWriteTokens",
    "cache_creation_ephemeral_5m_input_tokens": "x_CacheWriteTokens",
}
TOKEN_SUFFIXES = (
    ("-cache-creation", "cache_creation"),
    ("_cache_creation", "cache_creation"),
    ("-cache_creation", "cache_creation"),
    ("-cache-write", "cache_write"),
    ("_cache_write", "cache_write"),
    ("-cached-input", "cached_input"),
    ("_cached_input", "cached_input"),
    ("-cache-read", "cache_read"),
    ("_cache_read", "cache_read"),
    ("-output", "output"),
    ("-input", "input"),
)


@dataclass(frozen=True)
class NormalizedExport:
    cost_csv: str | None
    unpriced_records: list[dict[str, Any]]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_exporter_records(path: Path) -> list[dict[str, Any]]:
    """Read the exporter's JSON array (default) or CSV sink output."""
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"{path.name}: input exceeds the {MAX_BYTES // (1024 * 1024)} MiB limit")
    content = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        records = json.loads(content, parse_float=Decimal, object_pairs_hook=_unique_object)
        if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
            raise ValueError("JSON input must be an array of records")
    elif path.suffix.lower() == ".csv":
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        headers = reader.fieldnames or []
        if not headers or len(headers) != len(set(headers)):
            raise ValueError("CSV input has missing or duplicate column headers")
        records = []
        for line, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV record at line {line} has a different number of fields from the header")
            records.append(row)
    else:
        raise ValueError("Input must be .json or .csv")
    if len(records) > MAX_ROWS:
        raise ValueError(f"Input exceeds the {MAX_ROWS:,} row limit")
    if not records:
        raise ValueError("Input contains no records")
    return records


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _bucket(value: Any) -> str | None:
    key = re.sub(r"[\s-]+", "_", _text(value).lower())
    return TOKEN_FIELDS.get(key)


def _token_bucket(record: dict[str, Any]) -> tuple[str | None, str | None]:
    candidates: set[str] = set()
    model_hint = None
    unrecognized_token_type = False
    for name in ("x_TokenType", "SkuMeter", "SkuId"):
        value = _text(record.get(name))
        if not value:
            continue
        mapped = _bucket(value)
        if mapped:
            candidates.add(mapped)
            continue
        if name == "x_TokenType":
            unrecognized_token_type = True
        for suffix, alias in TOKEN_SUFFIXES:
            if value.lower().endswith(suffix):
                candidates.add(TOKEN_FIELDS[alias])
                if name in ("SkuMeter", "SkuId"):
                    model_hint = value[:-len(suffix)].rstrip("-_ ")
                break
    if len(candidates) > 1:
        raise ValueError("token bucket fields disagree")
    if candidates and unrecognized_token_type:
        raise ValueError("x_TokenType is not a recognised token bucket")
    return next(iter(candidates), None), model_hint


def _model_name(record: dict[str, Any], model_hint: str | None) -> str:
    supplied = _text(record.get("x_Model"))
    if supplied:
        if model_hint and supplied != model_hint:
            raise ValueError("x_Model conflicts with the model in SkuId or SkuMeter")
        return supplied
    if model_hint:
        return model_hint
    sku = _text(record.get("SkuId"))
    if sku:
        return sku
    service = _text(record.get("ServiceName"))
    if service.lower() not in {"openai", "openai api", "anthropic", "anthropic api"}:
        return service
    return ""


def _normalise_record(record: dict[str, Any]) -> dict[str, Any]:
    row = dict(record)
    providers = {_text(record.get(name)) for name in ("ProviderName", "ServiceProviderName", "Provider")}
    providers.discard("")
    if len(providers) != 1:
        raise ValueError("Provider, ProviderName and ServiceProviderName must identify one provider")
    row["ProviderName"] = providers.pop()

    bucket, model_hint = _token_bucket(record)
    if bucket:
        quantity = _text(record.get("ConsumedQuantity"))
        unit = _text(record.get("ConsumedUnit"))
        if quantity:
            if unit.lower() != "tokens":
                raise ValueError("a recognised token bucket must have ConsumedUnit=tokens")
            if not re.fullmatch(r"\d{1,15}", quantity):
                raise ValueError("token ConsumedQuantity must be a nonnegative integer with at most 15 digits")
            row[bucket] = quantity
        model = _model_name(record, model_hint)
        if model:
            row["x_Model"] = model
    return row


def _csv_cell(value: Any) -> str:
    return _text(value)


def convert_exporter_records(records: list[dict[str, Any]]) -> NormalizedExport:
    """Map exporter fields and token buckets; keep unpriced rows separate, never as zero."""
    if not records or len(records) > MAX_ROWS:
        raise ValueError(f"Expected between 1 and {MAX_ROWS:,} exporter records")
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("Every exporter record must be an object")

    cost_records = []
    unpriced_records = []
    for index, record in enumerate(records, 1):
        billed, effective = _text(record.get("BilledCost")), _text(record.get("EffectiveCost"))
        if not billed and not effective:
            unpriced_records.append(record)
            continue
        if not billed or not effective:
            raise ValueError(f"record {index}: BilledCost and EffectiveCost must both be present or both be empty")
        try:
            cost_records.append(_normalise_record(record))
        except ValueError as error:
            raise ValueError(f"record {index}: {error}") from error

    if not cost_records:
        return NormalizedExport(None, unpriced_records)

    columns = list(dict.fromkeys(key for record in records for key in record))
    for column in ("ProviderName", "x_Model", "x_InputTokens", "x_OutputTokens",
                   "x_CachedInputTokens", "x_CacheWriteTokens"):
        if any(column in record for record in cost_records) and column not in columns:
            columns.append(column)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: _csv_cell(value) for key, value in record.items()} for record in cost_records)
    cost_csv = output.getvalue()
    parse_files([{"name": "focus-exporter.csv", "content": cost_csv}], "focus-exporter")
    return NormalizedExport(cost_csv, unpriced_records)


def _write_outputs(input_path: Path, output_path: Path, unpriced_path: Path | None) -> int:
    input_path, output_path = input_path.resolve(), output_path.resolve()
    unpriced_path = unpriced_path.resolve() if unpriced_path else None
    if input_path in (output_path, unpriced_path) or (unpriced_path and output_path == unpriced_path):
        raise ValueError("Input, cost CSV and unpriced sidecar must use different paths")

    result = convert_exporter_records(load_exporter_records(input_path))
    if result.unpriced_records and unpriced_path is None:
        raise ValueError(f"{len(result.unpriced_records)} unpriced records need --unpriced-output; no output was written")
    if result.cost_csv is None and unpriced_path is None:
        raise ValueError("No cost-bearing records were found; no output was written")

    if result.cost_csv is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.cost_csv, encoding="utf-8", newline="")
    if unpriced_path:
        unpriced_path.parent.mkdir(parents=True, exist_ok=True)
        unpriced_path.write_text(
            json.dumps(result.unpriced_records, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
            newline="",
        )
    print(f"Converted {sum(1 for _ in csv.DictReader(io.StringIO(result.cost_csv or '')))} cost-bearing records.")
    if result.unpriced_records:
        print(f"Preserved {len(result.unpriced_records)} unpriced records in {unpriced_path}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="focus-exporter .json or .csv output")
    parser.add_argument("--output", type=Path, required=True, help="normalized CSV for the local dashboard")
    parser.add_argument("--unpriced-output", type=Path, help="JSON sidecar for records without billed and effective cost")
    args = parser.parse_args(argv)
    try:
        return _write_outputs(args.input, args.output, args.unpriced_output)
    except (OSError, ValueError, ImportFailure, json.JSONDecodeError, csv.Error) as error:
        print(f"focus-exporter adapter: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
