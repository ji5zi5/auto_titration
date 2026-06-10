#!/usr/bin/env python3
"""Local web dashboard server for the science-fair titration app.

The static website can be opened with a plain http.server, but this small
stdlib-only server adds read-only JSON endpoints for the latest collected CSV so
that the dashboard can poll live feature rows during a demonstration.
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import posixpath
import sys
import time
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEBSITE_DIR = ROOT / "website"
DEFAULT_CSV = ROOT / "data" / "raw" / "windows-live-mini2-visible.csv"


@dataclass(frozen=True)
class ServerConfig:
    root: Path
    website_dir: Path
    default_csv: Path
    live_stream_base: str


def _placeholder_bmp_bytes(width: int = 320, height: int = 180) -> bytes:
    """Return a tiny valid 24-bit BMP shown until the collector writes frames."""

    row_stride = ((width * 3 + 3) // 4) * 4
    pixel_bytes = row_stride * height
    file_size = 14 + 40 + pixel_bytes

    header = bytearray()
    header.extend(b"BM")
    header.extend(file_size.to_bytes(4, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend((54).to_bytes(4, "little"))
    header.extend((40).to_bytes(4, "little"))
    header.extend(width.to_bytes(4, "little", signed=True))
    header.extend(height.to_bytes(4, "little", signed=True))
    header.extend((1).to_bytes(2, "little"))
    header.extend((24).to_bytes(2, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend(pixel_bytes.to_bytes(4, "little"))
    header.extend((2835).to_bytes(4, "little", signed=True))
    header.extend((2835).to_bytes(4, "little", signed=True))
    header.extend((0).to_bytes(4, "little"))
    header.extend((0).to_bytes(4, "little"))

    pixels = bytearray()
    for y in range(height):
        row = bytearray()
        for x in range(width):
            checker = ((x // 24) + (y // 24)) % 2
            shade = 24 if checker else 16
            # BMP stores BGR. Keep the placeholder dark but valid.
            row.extend((shade + 8, shade + 4, shade))
        row.extend(b"\x00" * (row_stride - width * 3))
        pixels.extend(row)

    return bytes(header + pixels)


def ensure_live_preview_placeholders(website_dir: Path = WEBSITE_DIR) -> None:
    """Reset live preview files so the browser never starts on blank or stale data."""

    live_dir = website_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)

    visible_path = live_dir / "visible.bmp"
    visible_tmp = visible_path.with_suffix(".bmp.tmp")
    visible_tmp.write_bytes(_placeholder_bmp_bytes())
    os.replace(visible_tmp, visible_path)

    thermal_bmp_path = live_dir / "thermal.bmp"
    thermal_bmp_tmp = thermal_bmp_path.with_suffix(".bmp.tmp")
    thermal_bmp_tmp.write_bytes(_placeholder_bmp_bytes(width=256, height=192))
    os.replace(thermal_bmp_tmp, thermal_bmp_path)

    thermal_path = live_dir / "thermal.json"
    thermal_tmp = thermal_path.with_suffix(".json.tmp")
    thermal_tmp.write_text(
        json.dumps(
            {
                "frame_id": None,
                "time_s": None,
                "updated_epoch_s": time.time(),
                "temperature_avg_c": None,
                "temperature_min_c": None,
                "temperature_max_c": None,
                "temperature_delta_c": None,
                "temperature_std_c": None,
                "status_label": "waiting",
                "status_confidence": None,
                "sync_quality": "waiting",
                "sync_offset_ms": None,
                "thermal_mode": "waiting",
                "raw_avg": None,
                "raw_min": None,
                "raw_max": None,
                "raw_delta": None,
                "visible_capture_index": "",
                "mini2_capture_index": "",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(thermal_tmp, thermal_path)


def _json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def safe_repo_path(root: Path, requested: str | None, *, default: Path | None = None) -> Path:
    """Resolve a browser-provided relative path without allowing traversal."""

    if not requested:
        if default is None:
            raise ValueError("path is required")
        candidate = default
    else:
        raw = unquote(requested).replace("\\", "/").strip()
        if not raw:
            if default is None:
                raise ValueError("path is required")
            candidate = default
        elif raw.startswith("/") or ":" in raw.split("/", 1)[0]:
            raise ValueError("only repository-relative paths are allowed")
        else:
            candidate = root / raw
    resolved = candidate.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError("path must stay inside the repository")
    return resolved


def read_csv_tail(csv_path: Path, *, limit: int = 360) -> dict[str, Any]:
    if not csv_path.exists():
        return {
            "exists": False,
            "path": str(csv_path),
            "row_count": 0,
            "rows": [],
            "latest": None,
            "summary": None,
            "mtime": None,
        }
    rows: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
    summary_path = csv_path.with_suffix(".summary.json")
    summary: dict[str, Any] | None = None
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            summary = {"error": f"summary json parse failed: {exc}"}
    tail = rows[-max(1, limit) :]
    return {
        "exists": True,
        "path": str(csv_path),
        "row_count": len(rows),
        "rows": tail,
        "latest": tail[-1] if tail else None,
        "summary": summary,
        "mtime": csv_path.stat().st_mtime,
        "mtime_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(csv_path.stat().st_mtime)),
    }


def list_csv_files(root: Path, directory: Path, *, limit: int = 80) -> list[dict[str, Any]]:
    if not directory.exists() or not directory.is_dir():
        return []
    files = sorted(directory.rglob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "mtime": path.stat().st_mtime,
        }
        for path in files
    ]


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AutoTitrationDashboard/1.0"

    @property
    def config(self) -> ServerConfig:
        return self.server.config  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401 - keep http.server shape.
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802 - http.server API.
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            _json_response(self, {"ok": True, "root": str(self.config.root), "default_csv": str(self.config.default_csv)})
            return
        if parsed.path == "/api/live":
            self._handle_live(parsed.query)
            return
        if parsed.path == "/api/files":
            self._handle_files(parsed.query)
            return
        if self._should_proxy_to_live_collector(parsed.path):
            self._proxy_to_live_collector("GET")
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802 - http.server API.
        parsed = urlparse(self.path)
        if self._should_proxy_to_live_collector(parsed.path):
            if not self._origin_allowed_for_mutation():
                self.send_error(HTTPStatus.FORBIDDEN.value, "cross-origin POSTs are restricted to this dashboard origin")
                return
            self._proxy_to_live_collector("POST")
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def do_OPTIONS(self) -> None:  # noqa: N802 - browser preflight.
        parsed = urlparse(self.path)
        if self._should_proxy_to_live_collector(parsed.path):
            if not self._origin_allowed_for_mutation():
                self.send_error(HTTPStatus.FORBIDDEN.value, "cross-origin requests are restricted to this dashboard origin")
                return
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self._send_dashboard_cors_headers()
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND.value)

    def _should_proxy_to_live_collector(self, path: str) -> bool:
        return path in {
            "/stream/visible.mjpg",
            "/stream/thermal.mjpg",
            "/stream/events",
            "/api/collector-health",
            "/api/settings",
            "/api/csv",
            "/api/csv/status",
            "/api/csv/start",
            "/api/csv/stop",
            "/api/pump/dispense",
            "/api/pump/retract",
            "/api/pump/stop",
            "/api/mobile/status",
            "/api/mobile/pair",
            "/api/mobile/ingest",
            "/api/roi-click",
            "/api/roi-rect",
            "/api/roi-polygon",
            "/api/roi-lock",
            "/api/roi-unlock",
            "/api/roi-auto-candidate",
            "/api/chemistry/constants/lookup",
        }

    def _origin_allowed_for_mutation(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        try:
            parsed_origin = urlparse(origin)
            parsed_host = urlparse(f"//{self.headers.get('Host', '')}")
        except Exception:
            return False
        origin_host = (parsed_origin.hostname or "").lower()
        request_host = (parsed_host.hostname or "").lower()
        if not origin_host or not request_host:
            return False
        if parsed_origin.scheme != "http":
            return False
        origin_port = parsed_origin.port or (443 if parsed_origin.scheme == "https" else 80)
        request_port = parsed_host.port or self.server.server_address[1]
        return origin_host == request_host and origin_port == request_port

    def _send_dashboard_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed_for_mutation():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _proxy_to_live_collector(self, method: str) -> None:
        base = self.config.live_stream_base.rstrip("/")
        target_url = f"{base}{self.path}"
        body = None
        headers: dict[str, str] = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length > 0 else b""
            content_type = self.headers.get("Content-Type")
            if content_type:
                headers["Content-Type"] = content_type
        request = Request(target_url, data=body, method=method, headers=headers)
        response_started = False
        try:
            with urlopen(request, timeout=35) as response:  # noqa: S310 - local collector proxy only.
                self.send_response(response.status)
                self._send_dashboard_cors_headers()
                for key, value in response.headers.items():
                    lower = key.lower()
                    if lower in {"connection", "transfer-encoding", "server", "date", "access-control-allow-origin", "vary"}:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                response_started = True
                if parsed_path := urlparse(self.path).path:
                    if parsed_path == "/stream/events":
                        while True:
                            line = response.readline()
                            if not line:
                                break
                            self.wfile.write(line)
                            self.wfile.flush()
                    elif parsed_path.startswith("/stream/"):
                        read_chunk = getattr(response, "read1", response.read)
                        while True:
                            chunk = read_chunk(2048)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    else:
                        while True:
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except (OSError, URLError) as exc:
            if response_started:
                return
            _json_response(
                self,
                {
                    "ok": False,
                    "error": f"수집기(Collector)가 아직 실행 중이 아니거나 포트가 닫혀 있습니다: {self.config.live_stream_base}",
                    "detail": f"live collector proxy failed: {exc}",
                    "live_stream_base": self.config.live_stream_base,
                    "action_hints": [
                        "21번 실행 창에서 Auto Titration Collector 창이 열렸는지 확인하세요.",
                        "Collector 창에 Python/camera/DLL 오류가 있으면 그 오류가 먼저 해결되어야 합니다.",
                    ],
                },
                HTTPStatus.BAD_GATEWAY,
            )

    def _handle_live(self, query: str) -> None:
        params = parse_qs(query)
        requested = params.get("path", [None])[0]
        limit_raw = params.get("limit", ["360"])[0]
        try:
            limit = max(1, min(5000, int(limit_raw)))
            csv_path = safe_repo_path(self.config.root, requested, default=self.config.default_csv)
            payload = read_csv_tail(csv_path, limit=limit)
            _json_response(self, payload)
        except (OSError, ValueError) as exc:
            _json_response(self, {"exists": False, "error": str(exc), "rows": [], "row_count": 0}, HTTPStatus.BAD_REQUEST)

    def _handle_files(self, query: str) -> None:
        params = parse_qs(query)
        requested = params.get("root", ["data/raw"])[0]
        try:
            directory = safe_repo_path(self.config.root, requested, default=self.config.root / "data" / "raw")
            _json_response(self, {"files": list_csv_files(self.config.root, directory)})
        except (OSError, ValueError) as exc:
            _json_response(self, {"files": [], "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _serve_static(self, raw_path: str) -> None:
        request_path = posixpath.normpath(unquote(raw_path).split("?", 1)[0])
        if request_path in {"/", "."}:
            request_path = "/index.html"
        if request_path.startswith("../") or "/../" in request_path:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        file_path = (self.config.website_dir / request_path.lstrip("/")).resolve()
        try:
            file_path.relative_to(self.config.website_dir.resolve())
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if file_path.name == "index.html":
            text = file_path.read_text(encoding="utf-8")
            injection = "  <script>window.AUTO_TITRATION_STREAM_BASE = '.';</script>\n"
            if "window.AUTO_TITRATION_STREAM_BASE" not in text:
                text = text.replace('  <script src="app.js"></script>', injection + '  <script src="app.js"></script>')
            body = text.encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(
    host: str,
    port: int,
    *,
    csv_path: Path = DEFAULT_CSV,
    live_stream_base: str = "http://127.0.0.1:8766",
) -> ThreadingHTTPServer:
    ensure_live_preview_placeholders(WEBSITE_DIR)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.config = ServerConfig(  # type: ignore[attr-defined]
        root=ROOT,
        website_dir=WEBSITE_DIR,
        default_csv=csv_path,
        live_stream_base=live_stream_base,
    )
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--csv", default=None, help="repository-relative default CSV path for /api/live")
    parser.add_argument("--live-stream-base", default="http://127.0.0.1:8766", help="collector MJPEG/SSE base URL proxied by the dashboard server")
    parser.add_argument("--open", action="store_true", help="open the dashboard URL in a browser")
    args = parser.parse_args(argv)
    csv_path = safe_repo_path(ROOT, args.csv, default=DEFAULT_CSV)
    server = build_server(args.host, args.port, csv_path=csv_path, live_stream_base=args.live_stream_base)
    url = f"http://{args.host}:{args.port}/"
    print(f"Dashboard server: {url}")
    print(f"Default live CSV: {csv_path}")
    print(f"Live collector proxy: {args.live_stream_base}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
