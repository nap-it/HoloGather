#!/usr/bin/env python3
"""
Serve the dataset validation dashboard with HTTP range-request support.

Range requests (RFC 7233) are required for HTML5 video seeking — without them
the browser must buffer the whole file before playback and seeking is broken.
Python's built-in handler does not support ranges, so we add partial-content
handling here. Serves the repo root, so pages live under `/pages/` and videos
at `/recordings/<recording>/validation_rgb.mp4`.

Usage:
    python3 scripts/serve_dashboard.py [--port 8080]
"""

import argparse
import http.server
import json
import os
import re
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _recordings_path() -> Path:
    """Recordings folder from config.json (relative paths resolved against the
    repo root). Videos are served from here under the /recordings/ URL prefix."""
    cfg = ROOT / "config.json"
    raw = "../publisher/recordings"
    if cfg.exists():
        try:
            raw = json.loads(cfg.read_text()).get("recordings_path", raw)
        except Exception:
            pass
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p).resolve()


class RangeHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Serves the repo root, maps the /recordings/ URL prefix to the configured
    recordings folder, and adds partial-content (range) responses so the browser
    can stream/seek video without downloading the whole file first."""

    recordings_path: Path = ROOT / "recordings"  # overridden in main()

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/recordings/"):
            rel = clean[len("/recordings/"):].lstrip("/")
            target = (self.recordings_path / rel).resolve()
            # keep the mapping inside the recordings folder (no path traversal)
            if str(target).startswith(str(self.recordings_path.resolve())):
                return str(target)
        return super().translate_path(path)

    def do_GET(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            super().do_GET()
            return

        range_header = self.headers.get("Range")
        if not range_header:
            super().do_GET()
            return

        file_size = os.path.getsize(path)
        m = re.search(r"bytes=(\d+)-(\d*)", range_header)
        if not m:
            super().do_GET()
            return

        byte1 = int(m.group(1))
        byte2 = int(m.group(2)) if m.group(2) else file_size - 1
        byte2 = min(byte2, file_size - 1)
        length = byte2 - byte1 + 1

        with open(path, "rb") as f:
            f.seek(byte1)
            data = f.read(length)

        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {byte1}-{byte2}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, *_):
        pass  # silence per-request logging

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            pass


def main():
    parser = argparse.ArgumentParser(description="Serve the validation dashboard")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    os.chdir(ROOT)
    RangeHTTPRequestHandler.recordings_path = _recordings_path()
    url = f"http://localhost:{args.port}/pages/index.html"
    print(f"\n  Dashboard    → {url}")
    print(f"  Recordings   → {RangeHTTPRequestHandler.recordings_path}\n")
    webbrowser.open(url)

    with http.server.HTTPServer(("", args.port), RangeHTTPRequestHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")


if __name__ == "__main__":
    main()
