"""Build the static, website-ready demo of DataHub - FinOps.

    python demo/build_demo.py                      # writes dist/demo/
    python demo/build_demo.py --zip                # also writes dist/DataHub-FinOps-demo.zip
    python demo/build_demo.py --pyodide-tgz FILE   # offline: use an already downloaded pyodide-0.29.5.tgz
    python demo/build_demo.py --back-link /#solutions   # adds a link back to the hosting site

The output is plain static files. The same Python as the local app runs in the browser through
Pyodide, so there is no server, and files a visitor imports are never uploaded. Both bundled
datasets are invented: the AI scenario and demo/cloud_scenario.py. The anonymised official cloud
sample used by the local app is not published in the demo.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "app"
sys.path.insert(0, str(APP))

sys.path.insert(0, str(REPO / "demo"))

from ai_sample import sample_csv  # noqa: E402
from cloud_scenario import scenario_csv  # noqa: E402
from consumption_sample import load_consumption_sample  # noqa: E402

PYODIDE_VERSION = "0.29.5"
PYODIDE_URL = f"https://registry.npmjs.org/pyodide/-/pyodide-{PYODIDE_VERSION}.tgz"
PYODIDE_INTEGRITY = "sha512-TkYrUv9m8QmfImADKRmpwZulL48E0uUaBSO+dvRQKyAJc0qh9gu7jn8btyHPh3NZm1r2IH2YrJhIr7Q2B9urAw=="
PYODIDE_FILES = ["pyodide.mjs", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]

# index.html and dashboard.js text that describes the local-only app and is wrong for a hosted demo.
HTML_EDITS = [
    ("<title>DataHub - FinOps | Cloud and AI cost prototype</title>",
     '<title>DataHub - FinOps | Online demo</title>\n  <link rel="icon" href="data:,">'),
    ('<script type="module" src="dashboard.js"></script>',
     '<link rel="stylesheet" href="demo.css">\n  <script src="demo-shim.js"></script>\n'
     '  <script type="module" src="dashboard.js"></script>'),
    ('<span class="local-dot" aria-hidden="true"></span> Local prototype\n      <p>No cloud connection.<br>Fabric is the first deployment path.</p>',
     '<span class="local-dot" aria-hidden="true"></span> Online demo\n      <p>Invented data. No sign-in.<br>Runs in your browser; nothing is uploaded.</p>'),
    ('<main id="main" tabindex="-1">',
     '<main id="main" tabindex="-1">\n    <p class="demo-strip"><strong>Online demo</strong>'
     '<span>No sign-in. All data is invented and processed in your browser.</span>{back_link}</p>'),
    ("Files are processed on this machine, kept in memory, and never sent to a cloud service.",
     "Files are processed in your browser, kept in memory, and never uploaded."),
    ("Cloud &amp; AI cost · Prototype / local only", "Cloud &amp; AI cost · Online demo with invented data"),
    (">Load official cloud sample</button>", ">Load multi-cloud scenario</button>"),
    ('<a href="sample.csv" download="focus_sample.csv">Download the official sample CSV</a>',
     '<a href="sample.csv" download="multi-cloud-scenario.csv">Download the multi-cloud scenario CSV</a>'),
    ('The separate official cloud sample comes from <a href="https://github.com/FinOps-Open-Cost-and-Usage-Spec/FOCUS-Sample-Data" target="_blank" rel="noreferrer">FinOps Foundation FOCUS Sample Data</a>, <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noreferrer">CC BY 4.0</a>, with original values and dates.',
     "The multi-cloud scenario is also invented: made-up accounts, resources, tags and amounts, with public "
     "service and region names for readability. It is not provider pricing or billing data."),
]
JS_EDITS = [
    ("Restarts restore the AI scenario.", "Reloading the page restores the AI scenario.", 1),
    ('"Official cloud cost sample"', '"Synthetic multi-cloud scenario"', 3),
    ('"1,000 anonymised rows / AWS, Microsoft & Oracle / Sep-Oct 2024. Partial data, not a complete bill."',
     '"AWS / Azure / Google Cloud / Oracle. Invented charges for Oct 2026, not actual prices or bills."', 1),
]


def replace_once(text: str, old: str, new: str, label: str, count: int = 1) -> str:
    if text.count(old) != count:
        raise SystemExit(f"{label}: expected {count} match(es) for {old[:60]!r}")
    return text.replace(old, new)


def back_link_html(url: str | None) -> str:
    if not url:
        return ""
    if not url.startswith(("/", "https://")) or any(char in url for char in "\"'<>"):
        raise SystemExit("--back-link must be a site path or https URL without quotes or angle brackets.")
    return f' <a href="{url}">All dashboard demos</a>'


def fetch_pyodide(cache: Path, local: Path | None) -> Path:
    if local is None:
        local = cache / f"pyodide-{PYODIDE_VERSION}.tgz"
        if not local.exists():
            cache.mkdir(parents=True, exist_ok=True)
            print(f"Downloading {PYODIDE_URL}")
            with urllib.request.urlopen(PYODIDE_URL, timeout=120) as response:
                local.write_bytes(response.read())
    digest = "sha512-" + base64.b64encode(hashlib.sha512(local.read_bytes()).digest()).decode()
    if digest != PYODIDE_INTEGRITY:
        raise SystemExit(f"{local} does not match the pinned Pyodide {PYODIDE_VERSION} integrity hash.")
    return local


def build(out: Path, tgz: Path, back_link: str | None = None) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "python").mkdir(parents=True)
    (out / "pyodide").mkdir()

    web = APP / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    for old, new in HTML_EDITS:
        html = replace_once(html, old, new.replace("{back_link}", back_link_html(back_link)), "index.html")
    (out / "index.html").write_bytes(html.encode("utf-8"))
    js = (web / "dashboard.js").read_text(encoding="utf-8")
    for old, new, count in JS_EDITS:
        js = replace_once(js, old, new, "dashboard.js", count)
    (out / "dashboard.js").write_bytes(js.encode("utf-8"))
    for name in ("charts.js", "dashboard.css"):
        shutil.copy2(web / name, out / name)
    for name in ("demo-shim.js", "demo.css"):
        shutil.copy2(REPO / "demo" / name, out / name)

    for source in (APP / "focus_core.py", APP / "ai_sample.py", REPO / "demo" / "demo_api.py"):
        shutil.copy2(source, out / "python" / source.name)

    (out / "sample.csv").write_bytes(scenario_csv().encode("utf-8"))
    (out / "ai-sample.csv").write_bytes(sample_csv().encode("utf-8"))
    (out / "native.json").write_text(
        json.dumps(load_consumption_sample(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with tarfile.open(tgz) as archive:
        for name in PYODIDE_FILES:
            member = archive.extractfile(f"package/{name}")
            (out / "pyodide" / name).write_bytes(member.read())
    (out / "pyodide" / "NOTICE.txt").write_text(
        f"Pyodide {PYODIDE_VERSION} (MPL-2.0), unmodified. Source: https://github.com/pyodide/pyodide\n"
        "Licence: https://www.mozilla.org/en-US/MPL/2.0/\n",
        encoding="utf-8")
    sums = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out).as_posix()}"
            for path in sorted(out.rglob("*")) if path.is_file()]
    (out / "SHA256SUMS.txt").write_bytes(("\n".join(sums) + "\n").encode("utf-8"))


def zip_dir(out: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(out).as_posix())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=REPO / "dist" / "demo")
    parser.add_argument("--pyodide-tgz", type=Path)
    parser.add_argument("--zip", action="store_true")
    parser.add_argument("--back-link", help="optional link to the hosting site's demo list, e.g. /#solutions")
    args = parser.parse_args()
    build(args.out, fetch_pyodide(REPO / ".cache", args.pyodide_tgz), args.back_link)
    size = sum(path.stat().st_size for path in args.out.rglob("*") if path.is_file())
    print(f"Demo written to {args.out} ({size / 1e6:.1f} MB)")
    if args.zip:
        target = args.out.parent / "DataHub-FinOps-demo.zip"
        zip_dir(args.out, target)
        print(f"Zip written to {target} ({target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
