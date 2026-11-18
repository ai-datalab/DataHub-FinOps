# focus-exporter compatibility sample

`sample.json` is synthetic data shaped like the JSON records produced by
[focus-exporter](https://github.com/baselinehq/focus-exporter). It contains OpenAI and Anthropic
token-bucket charges plus an Anthropic usage row with no matching billed cost. It is not a real
export, invoice, customer identifier or rate.

Convert it for the local dashboard from the repository root:

```powershell
python app\exporter_adapter.py samples\focus-exporter\sample.json `
  --output $env:TEMP\focus-exporter-costs.csv `
  --unpriced-output $env:TEMP\focus-exporter-unpriced.json
```

Import the resulting cost CSV using **Data sources**. The unpriced sidecar preserves usage-only
records separately; they are not assigned zero cost or included in dashboard totals. The adapter
does not install or run focus-exporter, call provider APIs, or handle credentials.
