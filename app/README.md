# DataHub - FinOps prototype

**Local prototype, not a supported product.** Fabric is the first cloud path; Azure and standalone
SharePoint remain planned. This prototype runs locally on sample or imported CSV data and does not
change any cloud resources.

## Run it

Python 3.10+ is the only dependency. From the repository root:

```powershell
python app\server.py
```

Open `http://127.0.0.1:8765`. Stop with Ctrl+C. Use `--port 8766` if the default port is busy.
The server binds only to loopback. Do not expose it through a proxy or public tunnel.
All browser tabs on this local server share one in-memory dataset; this is a single-user tool.

The initial dashboard uses a **synthetic AI FinOps scenario**: Claude/Anthropic, OpenAI and Azure
OpenAI, five illustrative model/deployment labels, four workloads and 31 days in October 2026.
These are not actual prices, rates, billing exports, measured savings or production usage.
The scenario generator is [ai_sample.py](ai_sample.py); its CSV is downloadable in the app.

Choose **Multi-cloud FinOps** in the **View** switch at the top (or **Official cloud sample** on Data
sources) for the separate
[official cross-vendor extract](../samples/focus/README.md): 1,000 unchanged rows from AWS,
Microsoft and Oracle. There are no Google Cloud rows in this extract. Its dates remain in 2024.
The two samples replace each other, not blend into a misleading combined total. The switch is shown only
while a bundled sample is loaded, so it never replaces your own imported CSV.

The **Consumption** section also uses the repository's bundled synthetic
[Consumption Central sample feeds](../samples/consumption/). They are independent of the FOCUS CSV
selection and stay loaded when that selection changes. They are illustrative test data, not live tenant
usage or invoices.

## What works

The UI follows the visual language of the [DataHub demo](https://ai-datalab.github.io/demo/copilot-datahub/),
chart first, with data tables folded behind "Show data table".

- **Cross-vendor view** (Portfolio, Spend & trends, Cost explorer, Models & tokens, Cost & evidence,
  Source coverage):
  vendor KPI cards with sparklines, daily stacked spend, a workload-by-model heatmap (service-by-vendor
  when the file has no model/workload labels), share-by-model and cumulative lines, a token-mix chart,
  billed-versus-effective and same-row list-versus-contracted cost/unit-price comparisons, charge-category mix, account,
  service, region, resource, SKU and tag-allocation breakdowns, per-vendor source snapshots and a FOCUS
  field-coverage heatmap. The dimension/value filters apply across compatible dashboard pages.
- **FOCUS consumption** (All vendors, Run-rate, one tab per vendor): what each vendor's models consumed and cost,
  cost by service/model/workload with tokens beside spend, and a straight-line month-to-date pace with an
  optional budget stored only in your browser. A complete month gets no projection, and charges dated
  outside their billing period are never projected.
- **Product usage** (Cowork / Work IQ, Copilot Studio, GitHub Copilot and Azure AI Foundry): source-native
  credits, tokens, cost bases, product breakdowns and feed coverage. Weekly Cowork, dated Studio tenant
  data, Studio month-to-date snapshots, GitHub daily usage, Foundry meter spend, Cost Management actual /
  amortized spend and monthly deployment-health snapshots remain separate. Currencies and unlike units
  are not combined; optional feeds can be empty without breaking other pages.
- **Licenses** (`#/consumption/licenses`): an estimated seat cost layer, kept apart from FOCUS and usage
  totals. Assigned seats (Microsoft 365 Copilot from `PeopleMetaData.csv`, GitHub Copilot from
  `GitHubUserMap.csv`) are multiplied by an effective-dated `LicenseRateCard.csv`. Seat counts are one
  snapshot applied to every month with usage and rates are not prorated. The sample rates are illustrative,
  not list prices; replace them with your agreement prices. A plan marked `Billed in FOCUS` is excluded from
  the estimate so seats are not counted twice. Seats with no credit usage are review candidates, not proof
  of inactivity, and Cowork credits are too partial a signal to flag Microsoft 365 seats at all. GitHub
  usage amounts have no currency column, so they are shown beside the seat estimate, never added to it.
- Billed cost, effective cost, negative charges, filters for period, vendor, service, currency, model and workload.
- Multi-file UTF-8 CSV import with structural validation and per-file row counts.
- Exact decimal aggregation, negative credits and strict currency separation.
- Whole-snapshot replacement: retrying an import does not append another copy.
- Charts fall back honestly when data is missing: no model, workload or token columns means a labelled
  empty state or a service-level view, never zeros.
- The same parser in a preview-first Fabric loader.

Cost per 1M tokens is a blended figure over rows that report all four counters. It is not a price
benchmark. Product-native usage currently uses bundled sample files, not a live Consumption Central
collector. Task-level attribution is not available in these sample feeds and is not inferred. Live Claude,
OpenAI or Consumption Central connectors, Fabric deployment and Power BI publishing are not built; the
app labels them "Not connected" or "Not deployed".

## Bring your own data

Use the [FOCUS data-generator directory](https://focus.finops.org/docs/implementation/get-started/get-started-with-focus-datasets/)
to enable your provider's export. Select every CSV partition for **one complete snapshot** together,
check the replacement confirmation, and choose **Validate & import**. Import replaces everything
currently shown, including the sample. It does not merge with earlier imports. Do not mix overlapping
exports from the same billing scope. The importer can reject identical files but cannot infer whether
different files overlap or whether a partition is missing.

The snapshot limit is 100 files, 20 MiB of UTF-8 content and 100,000 rows. Convert compressed exports
to CSV before selecting them. No Parquet, Excel, PDF extraction or AI conversion is implemented.
Uploads stay only in the local process's memory, not in the repository or browser storage.
Restarting restores the synthetic AI scenario. No cloud API is called.

Required columns:
`BilledCost`, `EffectiveCost`, `BillingCurrency`, `BillingAccountId`, `ServiceName`,
`BillingPeriodStart`, `BillingPeriodEnd`, `ChargePeriodStart`, `ChargePeriodEnd`,
and either `ProviderName` or `ServiceProviderName`.

The parser accepts quoted CSV, embedded newlines, UTF-8 BOMs and literal `NULL` for optional fields.
Costs must be finite decimals fitting `decimal(38,18)`. Times with an offset are normalised to UTC;
unqualified dates/timestamps are treated as UTC. Empty required values, invalid date ranges, malformed
rows and duplicate headers reject the **entire** snapshot. No bad rows are silently dropped.
Repeated charge rows are preserved: FOCUS does not guarantee row uniqueness.

### focus-exporter compatibility pilot

The local adapter accepts JSON or CSV output from
[focus-exporter](https://github.com/baselinehq/focus-exporter). It was checked against the
published `v0.0.0-20260811092817-2ff74a0ffb0e` output schema using only synthetic sample records;
it has not run the exporter or called provider APIs.

From the repository root, convert a sample or your own export:

```powershell
python app\exporter_adapter.py samples\focus-exporter\sample.json `
  --output $env:TEMP\focus-exporter-costs.csv `
  --unpriced-output $env:TEMP\focus-exporter-unpriced.json
```

Import the generated cost CSV through **Data sources**. The adapter maps `Provider` to
`ProviderName` and maps recognized token buckets in `SkuMeter`, `SkuId` or `x_TokenType` to the
prototype's per-row token fields. It validates the normalized CSV with the regular importer. Costs
from rows without both `BilledCost` and `EffectiveCost` are never set to zero: those original records
must be saved to the separate unpriced JSON sidecar. Rows are not considered complete just because a
token bucket is recognized; missing bucket counters remain unknown. Since the exporter emits one
token bucket per row, the prototype's all-four-counter cost-per-million metric will generally remain
unavailable; the adapter does not duplicate or infer counters to make that metric appear.

This is an interchange pilot, not an installer integration. It does not install or bundle
focus-exporter, generate provider setup screens, store credentials, or schedule collection. The
exporter itself is AGPL-3.0 with a commercial licensing option; review the applicable terms before
including it in a distributed installer or hosted service. No legal conclusion is implied here.

### AI fields

The prototype accepts these optional `x_` extension columns alongside the required cost columns:

| Column | Meaning |
|---|---|
| `x_Model` | Provider-reported model or deployment label |
| `x_Workload` | Your agent, application or workload label |
| `x_InputTokens` | Uncached input tokens, excluding cache-write tokens |
| `x_OutputTokens` | Output tokens |
| `x_CachedInputTokens` | Cache-read input tokens |
| `x_CacheWriteTokens` | Cache-creation/write input tokens |

The four token counters are disjoint, nonnegative integers. Missing counters remain unknown, not zero.
Coverage shows how many selected rows supply all four. Token totals sum the supplied values only.
Do not repeat whole-workload token counts on each billing line; aggregate cost and usage to a matching
grain first. These extension names are a prototype contract, not standard FOCUS columns.

### Real Claude and OpenAI sources

AI FinOps is core scope. Live collectors are the next ingestion step, not a requirement for using the
local CSV prototype. No credentials should be pasted into this app or committed to the repository.

- **Claude/Anthropic:** the [Usage and Cost Analytics API](https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api)
  supplies usage and cost separately with model/workspace dimensions. The current documented API
  is beta; it requires authorised admin/analytics credentials. Convert documented cost units carefully
  (the analytics API expresses amounts as decimal strings in cents).
- **OpenAI:** the [official Usage and Costs example](https://developers.openai.com/cookbook/examples/completions_usage_api)
  covers organisation-level usage and costs with admin credentials. Usage grouping and cost grouping
  do not necessarily share model-level granularity: preserve unresolved attribution instead of
  inventing per-model billed costs. Cached input can be included in total input; map the disjoint
  counters explicitly.
- **Cloud-hosted AI:** use the cloud bill for Azure OpenAI, Bedrock or Vertex charges. Never sum
  a reseller/cloud charge and a direct-provider charge for the same usage.
- **Seats and subscriptions:** Claude and ChatGPT subscriptions are distinct from API charges.
  Their invoices/enterprise billing need separate adapters; this prototype does not infer them from
  token telemetry.

The loader types optional `ListCost`, `ContractedCost`, `ListUnitPrice`, `ContractedUnitPrice`,
`ConsumedQuantity` and `PricingQuantity` as decimals, while retaining their matching units, charge
and pricing categories, commitment fields, resource/SKU identifiers and JSON tags. Common application,
environment, business-unit and cost-centre tag spellings are exposed as dimensions; the original row
remains in `RawRecord`. Quantity totals are shown only when the selected group has one consistent
unit. The explorer suggests up to 100 dimension values but accepts any exact value present in the
filtered source, so high-cardinality resource fields stay usable.

This is a minimal analytical projection, **not a FOCUS 1.4 conversion or conformance validator**.
Provider headers identify a column family, not a specific version. `EffectiveCost` is taken from the
source, not recalculated; it is not labelled "savings." List and contracted costs are compared on the
same rows where both are supplied, with coverage shown, and are not savings calculations. All amounts
are aggregated using decimals; chart
geometry and two-decimal display are approximations. Dates without rows are not filled with invented
costs. Sub-account display names are grouped for exploration, not financial reconciliation.

## First Fabric loader

The loader is authored for Fabric but has **not been run against a live workspace**.
It intentionally handles the same small snapshots as the local prototype on the Spark driver.
It is not the final distributed loader for large billing exports.

1. In a development Fabric workspace, create a notebook and attach a development Lakehouse as its
   default. Import [fabric_notebook.py](fabric_notebook.py), or paste its parameter and code cells.
2. Upload [focus_core.py](focus_core.py) and [fabric_loader.py](fabric_loader.py) into the notebook's
   built-in resources.
3. Upload the complete snapshot to `Files/focus_prototype/official-sample/` in that Lakehouse.
   The bundled `samples/focus/focus_sample.csv` is suitable for the first run. Alternatively, download
   the AI scenario from the local app and use a separate `ai-demo` source folder/identifier. For real data, use a
   different `source_id` and matching folder. The folder must contain only this snapshot's CSVs,
   including all its partitions; keep old exports and manifests outside it.
4. Set `complete_snapshot = True`, leave `apply_changes = False`, and run. Inspect totals separately
   for each currency.
5. Set `apply_changes = True` and rerun. The notebook writes the dedicated Delta table
   `focus_cost_prototype` in the Lakehouse's default schema, partitioned by `SourceId`, then checks
   its row count. A subsequent run atomically replaces that source's **complete history**; other
   sources stay unchanged. Do not run two writers for the same source concurrently.

File parsing and validation finish before the first write. The existing target must have the expected
schema and partitioning; it is never silently migrated. A table created by the earlier prototype
schema must be replaced deliberately in a development Lakehouse before using this expanded loader.
The loader does not delete source files.
The local dashboard does **not** query this table yet. Semantic-model publishing, the Power BI report,
app authentication, automatic exports, scheduling and SharePoint connections are subsequent work.
AI-prepared files are flagged, but source-document total reconciliation is not implemented.

## Checks

From the repository root:

```powershell
python -m pytest app\tests -q
```

Tests cover source totals, typed FOCUS fields and tag extraction, CSV edge cases, currency separation,
linked dimension filters, unit-safe quantities, rejected imports retaining the last good dataset,
chart aggregates summing back to the total, token-complete unit cost, run-rate rules, source-native
Consumption Central grains and currency bases, optional-feed states, local HTTP boundaries and the Fabric write contract. They do not prove a live
Spark/Delta execution; that requires the preview/readback steps above.

The longer [plan](../docs/PLAN.md) retains all three deployment paths.
