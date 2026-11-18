"""Loopback-only prototype. Run from anywhere with Python 3.10+; no packages required."""
from __future__ import annotations

import argparse
import json
import logging
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ai_sample import sample_csv
from consumption_sample import load_consumption_sample
from focus_core import ImportFailure, MAX_BYTES, dashboard, parse_files

ROOT = Path(__file__).resolve().parent
SAMPLE = ROOT.parent / "samples" / "focus" / "focus_sample.csv"
STATIC = {"/": ("index.html", "text/html"), "/dashboard.js": ("dashboard.js", "text/javascript"),
          "/charts.js": ("charts.js", "text/javascript"), "/dashboard.css": ("dashboard.css", "text/css")}


def sample_dataset(kind="ai"):
    if kind not in ("ai", "cloud"):
        raise ValueError("Choose the ai or cloud sample.")
    content = sample_csv() if kind == "ai" else SAMPLE.read_bytes().decode("utf-8")
    name = "ai-scenario.csv" if kind == "ai" else SAMPLE.name
    dataset = parse_files([{"name": name, "content": content}], f"{kind}-sample")
    dataset["sample"] = True
    dataset["sampleKind"] = kind
    return dataset


class FocusServer(HTTPServer):
    def __init__(self, address):
        super().__init__(address, Handler)
        self.dataset = sample_dataset()
        self.native_consumption = load_consumption_sample()

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(15)
        return connection, address


class Handler(BaseHTTPRequestHandler):
    server: FocusServer

    def send(self, body: bytes, content_type: str, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, status=200):
        self.send(json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json", status)

    def trusted(self, mutation=False):
        host = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != host:
            self.json({"error": "Use the printed 127.0.0.1 URL."}, 403)
            return False
        if mutation and self.headers.get("Origin") != f"http://{host}":
            self.json({"error": "Imports must originate from this local dashboard."}, 403)
            return False
        return True

    def do_GET(self):
        if not self.trusted():
            return
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            name, content_type = STATIC[parsed.path]
            self.send((ROOT / "web" / name).read_bytes(), content_type)
        elif parsed.path == "/api/dashboard":
            try:
                filters = {key: values[0] for key, values in parse_qs(parsed.query).items()}
                self.json(self.dashboard_payload(filters))
            except ValueError as error:
                self.json({"error": str(error)}, 400)
        elif parsed.path == "/sample.csv":
            self.send(SAMPLE.read_bytes(), "text/csv")
        elif parsed.path == "/ai-sample.csv":
            self.send(sample_csv().encode("utf-8"), "text/csv")
        elif parsed.path == "/favicon.ico":
            self.send(b"", "image/x-icon", 204)
        else:
            self.json({"error": "Not found."}, 404)

    def dashboard_payload(self, filters):
        result = dashboard(self.server.dataset, filters)
        result["nativeConsumption"] = self.server.native_consumption
        return result

    def do_POST(self):
        if not self.trusted(mutation=True):
            return
        if self.headers.get("Content-Type") != "application/json":
            self.json({"error": "Expected application/json."}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            # JSON escaping can increase the payload size; the parser caps decoded CSV bytes.
            if not 0 < length <= MAX_BYTES * 2:
                self.json({"error": "Request is empty or too large."}, 413)
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object.")
            if self.path == "/api/import":
                dataset = parse_files(payload.get("files"), payload.get("sourceId", "upload"))
                dataset["sample"] = False
            elif self.path == "/api/sample":
                dataset = sample_dataset(payload.get("kind", "ai"))
            else:
                self.json({"error": "Not found."}, 404)
                return
            # A rejected snapshot never replaces the last good dataset.
            self.server.dataset = dataset
            self.json(self.dashboard_payload({}))
        except ImportFailure as error:
            self.json({"error": "Import rejected. The previous dataset is unchanged.", "issues": error.issues}, 400)
        except (ValueError, TypeError, UnicodeError) as error:
            self.json({"error": f"Invalid import: {error}"}, 400)
        except (socket.timeout, TimeoutError):
            self.json({"error": "Upload timed out. Try a smaller set of files."}, 408)

    def log_message(self, message, *args):
        logging.info(message, *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with FocusServer(("127.0.0.1", args.port)) as server:
        print(f"DataHub - FinOps: http://127.0.0.1:{server.server_port}", flush=True)
        print("Local only. Synthetic AI scenario on startup; imports stay in memory until stopped.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
