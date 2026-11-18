"""The browser demo API must answer exactly like the local server."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "demo"))

import demo_api  # noqa: E402
from consumption_sample import load_consumption_sample  # noqa: E402
from focus_core import dashboard  # noqa: E402
from server import SAMPLE, sample_dataset  # noqa: E402

NATIVE = load_consumption_sample()


def start():
    demo_api.start(SAMPLE.read_text(encoding="utf-8"), json.dumps(NATIVE))


def call(method, path, query="", body=""):
    reply = json.loads(demo_api.handle(method, path, query, body))
    return reply["status"], reply["body"]


def expected(dataset, filters=None):
    result = dashboard(dataset, filters or {})
    result["nativeConsumption"] = NATIVE
    return json.loads(json.dumps(result, ensure_ascii=False))


def test_starts_on_the_ai_scenario_like_the_server():
    start()
    assert call("GET", "/api/dashboard") == (200, expected(sample_dataset("ai")))


def test_filters_and_sample_switch_match_the_server():
    start()
    status, body = call("POST", "/api/sample", body=json.dumps({"kind": "cloud"}))
    assert (status, body) == (200, expected(sample_dataset("cloud")))
    status, body = call("GET", "/api/dashboard", "provider=AWS")
    assert (status, body) == (200, expected(sample_dataset("cloud"), {"provider": "AWS"}))


def test_import_replaces_data_and_a_bad_import_keeps_the_last_good_one():
    start()
    csv_text = SAMPLE.read_text(encoding="utf-8")
    good = json.dumps({"files": [{"name": "mine.csv", "content": csv_text}], "sourceId": "upload"})
    status, body = call("POST", "/api/import", body=good)
    assert status == 200 and body["sample"] is False
    bad = json.dumps({"files": [{"name": "bad.csv", "content": "not,a,focus,file\n1,2,3,4\n"}]})
    status, body = call("POST", "/api/import", body=bad)
    assert status == 400 and body["error"].startswith("Import rejected") and body["issues"]
    assert call("GET", "/api/dashboard")[1]["sample"] is False


def test_errors_match_the_server_contract():
    start()
    assert call("GET", "/api/missing")[0] == 404
    assert call("POST", "/api/sample", body="[]")[0] == 400
    assert call("POST", "/api/sample", body=json.dumps({"kind": "other"}))[0] == 400
    assert call("POST", "/api/import", body="")[0] == 413
