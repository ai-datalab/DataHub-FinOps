"""Helpers for the Fabric notebook; importing this file does not require PySpark."""
from __future__ import annotations

from pathlib import Path

from focus_core import DECIMALS, FIELDS, MAX_BYTES, MAX_FILES, OPTIONAL_DECIMALS, TOKENS, ImportFailure, parse_files

TABLE = "focus_cost_prototype"


def read_snapshot(folder: Path, source_id: str) -> dict:
    if not folder.is_dir():
        raise ImportFailure([f"Snapshot folder does not exist: {folder}"])
    paths = sorted(folder.rglob("*"))
    files = [path for path in paths if path.is_file()]
    if any(path.suffix.lower() != ".csv" for path in files):
        raise ImportFailure(["The snapshot folder must contain only CSV files. Keep archives and manifests elsewhere."])
    if len(files) > MAX_FILES or sum(path.stat().st_size for path in files) > MAX_BYTES:
        raise ImportFailure(["Snapshot exceeds 100 files or 20 MiB. Use a distributed ingestion path for larger exports."])
    inputs = []
    for path in files:
        try:
            content = path.read_bytes().decode("utf-8")
        except UnicodeError as error:
            raise ImportFailure([f"{path.name}: save the file as UTF-8 CSV."]) from error
        # A stable ordinal makes filenames from different partition folders unambiguous.
        inputs.append({"name": f"{len(inputs):03d}-{path.name}", "content": content})
    return parse_files(inputs, source_id)


def write_snapshot(spark, dataset: dict) -> int:
    """Replace one explicitly named source atomically, retaining other sources."""
    from pyspark.sql.types import DecimalType, IntegerType, LongType, StringType, StructField, StructType

    schema = StructType([
        StructField(key, DecimalType(38, 18) if key in DECIMALS else
                    IntegerType() if key == "SourceRow" else
                    LongType() if key in TOKENS else StringType(), key in TOKENS or key in OPTIONAL_DECIMALS)
        for key in FIELDS
    ])
    frame = spark.createDataFrame(dataset["rows"], schema=schema)
    if spark.catalog.tableExists(TABLE):
        existing = spark.table(TABLE)
        expected = [(field.name, field.dataType) for field in schema]
        actual = [(field.name, field.dataType) for field in existing.schema]
        if actual != expected:
            raise ValueError(f"{TABLE} has an incompatible schema. No data was written.")
        detail = spark.sql(f"DESCRIBE DETAIL {TABLE}").first()
        if detail["format"] != "delta" or list(detail["partitionColumns"]) != ["SourceId"]:
            raise ValueError(f"{TABLE} must be a Delta table partitioned by SourceId. No data was written.")
        source_id = dataset["sourceId"]
        # The source identifier has already passed the parser's strict allowlist.
        (frame.write.format("delta").mode("overwrite")
         .option("replaceWhere", f"SourceId = '{source_id}'").saveAsTable(TABLE))
    else:
        (frame.write.format("delta").mode("errorifexists")
         .partitionBy("SourceId").saveAsTable(TABLE))
    return len(dataset["rows"])
