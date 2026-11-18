"""Build the static, website-ready demo of DataHub - FinOps.

    python demo/build_demo.py                      # writes dist/demo/
    python demo/build_demo.py --zip                # also writes dist/DataHub-FinOps-demo.zip
    python demo/build_demo.py --pyodide-tgz FILE   # offline: use an already downloaded pyodide-0.29.5.tgz

The output is plain static files. The same Python as the local app runs in the browser through
Pyodide, so there is no server, and files a visitor imports are never uploaded.
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

from ai_sample import sample_csv  # noqa: E402
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
     '<span class="local-dot" aria-hidden="true"></span> Online demo\n      <p>Sample data only.<br>Runs in your browser; nothing is uploaded.</p>'),
    ("Files are processed on this machine, kept in memory, and never sent to a cloud service.",
     "Files are processed in your browser, kept in memory, and never uploaded."),
    ("Cloud &amp; AI cost · Prototype / local only", "Cloud &amp; AI cost · Online demo with sample data"),
]
JS_EDITS = [("Restarts restore the AI scenario.", "Reloading the page restores the AI scenario.")]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected exactly one match for {old[:60]!r}")
    return text.replace(old, new)


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


def build(out: Path, tgz: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    (out / "python").mkdir(parents=True)
    (out / "pyodide").mkdir()

    web = APP / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    for old, new in HTML_EDITS:
        html = replace_once(html, old, new, "index.html")
    (out / "index.html").write_bytes(html.encode("utf-8"))
    js = (web / "dashboard.js").read_text(encoding="utf-8")
    for old, new in JS_EDITS:
        js = replace_once(js, old, new, "dashboard.js")
    (out / "dashboard.js").write_bytes(js.encode("utf-8"))
    for name in ("charts.js", "dashboard.css"):
        shutil.copy2(web / name, out / name)
    for name in ("demo-shim.js", "demo.css"):
        shutil.copy2(REPO / "demo" / name, out / name)

    for source in (APP / "focus_core.py", APP / "ai_sample.py", REPO / "demo" / "demo_api.py"):
        shutil.copy2(source, out / "python" / source.name)

    cloud = REPO / "samples" / "focus" / "focus_sample.csv"
    if cloud.read_bytes().startswith(b"\xef\xbb\xbf"):
        raise SystemExit("The cloud sample has a BOM; the browser would strip it and change the parse.")
    shutil.copy2(cloud, out / "sample.csv")
    (out / "ai-sample.csv").write_bytes(sample_csv().encode("utf-8"))
    (out / "native.json").write_text(
        json.dumps(load_consumption_sample(), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    with tarfile.open(tgz) as archive:
        for name in PYODIDE_FILES:
            member = archive.extractfile(f"package/{name}")
            (out / "pyodide" / name).write_bytes(member.read())
    (out / "pyodide" / "NOTICE.txt").write_text(
        f"Pyodide {PYODIDE_VERSION} (MPL-2.0), unmodified. Source: https://github.com/pyodide/pyodide\n",
        encoding="utf-8")


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
    args = parser.parse_args()
    build(args.out, fetch_pyodide(REPO / ".cache", args.pyodide_tgz))
    size = sum(path.stat().st_size for path in args.out.rglob("*") if path.is_file())
    print(f"Demo written to {args.out} ({size / 1e6:.1f} MB)")
    if args.zip:
        target = args.out.parent / "DataHub-FinOps-demo.zip"
        zip_dir(args.out, target)
        print(f"Zip written to {target} ({target.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
