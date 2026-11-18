# Fabric notebook source

# METADATA ********************
# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   }
# META }

# MARKDOWN ********************
# # FOCUS small-file prototype
# Attach a development Lakehouse as the default. Upload focus_core.py and
# fabric_loader.py to this notebook's built-in resources.
# Put one complete snapshot in Files/focus_prototype/<source_id>/.
# This notebook starts in preview mode. It is not a production ingestion pipeline.

# PARAMETERS CELL ********************
source_id = "official-sample"
complete_snapshot = False
apply_changes = False

# CELL ********************
from pathlib import Path
import re
import sys

import notebookutils

if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", source_id):
    raise ValueError("source_id must contain only letters, digits, underscores or hyphens.")
if not notebookutils.runtime.context.get("defaultLakehouseId"):
    raise RuntimeError("Attach a development Lakehouse as this notebook's default, then restart its session.")
if not complete_snapshot:
    raise ValueError("Place every partition in the snapshot folder, then set complete_snapshot = True.")

sys.path.insert(0, str(Path(notebookutils.nbResPath) / "builtin"))
from fabric_loader import TABLE, read_snapshot, write_snapshot
from focus_core import dashboard

folder = Path("/lakehouse/default/Files/focus_prototype") / source_id
dataset = read_snapshot(folder, source_id)

for currency in sorted({row["BillingCurrency"] for row in dataset["rows"]}):
    totals = dashboard(dataset, {"currency": currency})
    print(f"{currency}: {totals['rows']} rows; billed={totals['billed']}; effective={totals['effective']}")
for warning in dataset["warnings"]:
    print(f"Warning: {warning}")

# CELL ********************
if apply_changes:
    count = write_snapshot(spark, dataset)
    actual = spark.table(TABLE).where(f"SourceId = '{source_id}'").count()
    if actual != count:
        raise RuntimeError(f"Readback failed: wrote {count} rows, found {actual}. Check concurrent runs.")
    print(f"Saved {count} rows for {source_id} to {TABLE}. Other source partitions are unchanged.")
else:
    print(f"Preview only. Set apply_changes = True to replace this source's complete snapshot in {TABLE}.")
