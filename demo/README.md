# Online demo

A static build of DataHub - FinOps for a website. It needs no server: the dashboard's Python runs in the
browser through [Pyodide](https://pyodide.org/), and files a visitor imports are processed there and
never uploaded. It needs no sign-in. It opens on the synthetic AI scenario; the **View** switch loads an
invented multi-cloud scenario (`cloud_scenario.py`: AWS, Azure, Google Cloud and Oracle, October 2026).
Every bundled record is invented; the anonymised official sample used by the local app is not published.

## Build

```powershell
python demo\build_demo.py --zip
```

This writes `dist\demo\` (about 13 MB) and `dist\DataHub-FinOps-demo.zip` (about 6 MB). The first run
downloads Pyodide 0.29.5 from the npm registry and refuses it unless it matches the pinned SHA-512 hash.
Use `--pyodide-tgz <file>` to build offline from a copy you already hold. `--back-link /#solutions`
adds an "All dashboard demos" link for a hosting site. `SHA256SUMS.txt` lists every output file.

Check it locally, since browsers will not run it from a `file://` address:

```powershell
python -m http.server 8790 --directory dist\demo
```

## Put it on a website

Upload the contents of `dist\demo` to a folder on any static host, for example `https://example.com/finops/`.
Use only relative links; the demo works under any path. To show it inside another page:

```html
<iframe src="https://example.com/finops/" title="DataHub - FinOps demo"
        width="100%" height="900" loading="lazy" style="border:0"></iframe>
```

Hosting notes:

- Serve `.wasm` as `application/wasm` (most hosts, including GitHub Pages, already do) and enable gzip or
  brotli. The first visit downloads about 12 MB before the dashboard appears; later visits use the cache.
- If your site sets a Content-Security-Policy, the demo's folder needs
  `script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; connect-src 'self'; img-src 'self' data:`.
  This exact policy has been tested.
- The demo makes no network calls other than loading its own files.

## How it works

`demo/build_demo.py` copies `app/web` and the parser modules, adds `demo-shim.js` and `demo_api.py`,
writes the two invented scenarios, and precomputes `native.json` (the synthetic product-usage feeds) so
visitors do not download the raw CSVs.
`demo-shim.js` answers the dashboard's `/api/*` requests from `demo_api.py`, which mirrors
`app/server.py`; `demo/tests` checks that both give identical answers. The dashboard code is unchanged
apart from a few text edits that say "online demo" rather than "local prototype" and name the scenario.
