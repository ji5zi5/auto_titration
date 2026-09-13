import csv
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools.dashboard_server import DEFAULT_CSV, ROOT, build_server, ensure_live_preview_placeholders, read_csv_tail, safe_repo_path


class FakeLiveCollectorHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):  # noqa: N802
        if self.path in {"/api/settings", "/api/collector-health", "/api/mobile/status"}:
            if self.path == "/api/mobile/status":
                self._send_json({"ok": True, "mobile": {"enabled": True, "source": "android_mobile", "state": "streaming"}})
                return
            if self.path == "/api/collector-health":
                self._send_json(
                    {
                        "ok": True,
                        "collector_running": True,
                        "visible_stream_ready": True,
                        "thermal_stream_ready": True,
                        "metadata_ready": True,
                        "csv": {"recording": False, "row_count": 0, "state": "idle"},
                        "latest": {"frame_id": 1, "thermal_mode": "mini2_uvc_raw_official_roi_celsius"},
                        "action_hints": ["수집기, 스트림, 메타데이터가 동작 중입니다."],
                    }
                )
                return
            self._send_json({"ok": True, "settings": {"roi_auto_detect": "both"}})
            return
        if self.path == "/stream/visible.mjpg":
            first = b"--autotitrationframe\r\n"
            rest = (
                b"--autotitrationframe\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: 4\r\n\r\n"
                b"JPEG\r\n"
            )
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=autotitrationframe")
            self.end_headers()
            self.wfile.write(first)
            self.wfile.flush()
            time.sleep(0.2)
            self.wfile.write(rest)
            self.wfile.flush()
            return
        self.send_error(404)

    def do_POST(self):  # noqa: N802
        if self.path in {
            "/api/roi-click",
            "/api/roi-rect",
            "/api/roi-polygon",
            "/api/roi-lock",
            "/api/roi-auto-candidate",
            "/api/mobile/pair",
            "/api/mobile/ingest",
            "/api/pump/dispense",
            "/api/pump/retract",
            "/api/pump/stop",
            "/api/pump/reset",
        }:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            self._send_json({"ok": True, "path": self.path, "payload": payload})
            return
        if self.path == "/api/chemistry/constants/lookup":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            self._send_json({"ok": True, "path": self.path, "query": payload.get("query", "")})
            return
        self.send_error(404)

    def _send_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DashboardServerTests(unittest.TestCase):
    def test_safe_repo_path_rejects_traversal_and_absolute_paths(self):
        self.assertEqual(safe_repo_path(ROOT, "data/raw/example.csv"), (ROOT / "data/raw/example.csv").resolve())
        self.assertEqual(safe_repo_path(ROOT, None, default=DEFAULT_CSV), DEFAULT_CSV.resolve())
        with self.assertRaises(ValueError):
            safe_repo_path(ROOT, "../secret.csv")
        with self.assertRaises(ValueError):
            safe_repo_path(ROOT, "/tmp/secret.csv")

    def test_read_csv_tail_returns_latest_rows_and_summary(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            csv_path = Path(tmp) / "live.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["time_s", "thermal_roi_avg", "visible_color_delta"])
                writer.writeheader()
                for i in range(5):
                    writer.writerow({"time_s": i, "thermal_roi_avg": 20 + i, "visible_color_delta": i * 0.1})
            csv_path.with_suffix(".summary.json").write_text(json.dumps({"capture_span_fps": 24.98}), encoding="utf-8")

            payload = read_csv_tail(csv_path, limit=2)

        self.assertTrue(payload["exists"])
        self.assertEqual(payload["row_count"], 5)
        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["latest"]["thermal_roi_avg"], "24")
        self.assertEqual(payload["summary"]["capture_span_fps"], 24.98)

    def test_dashboard_launcher_exists_and_uses_local_server(self):
        launcher = Path("launchers/windows/21_open_dashboard_server.bat").read_text(encoding="utf-8")

        self.assertIn("tools\\dashboard_server.py", launcher)
        self.assertIn("http://127.0.0.1:%PORT%/", launcher)
        self.assertIn("DASHBOARD_HOST=0.0.0.0", launcher)
        self.assertIn("--host %DASHBOARD_HOST%", launcher)
        self.assertIn("LAN URL", launcher)
        self.assertIn("Windows Defender Firewall", launcher)
        self.assertIn('--live-stream-base "http://127.0.0.1:%LIVE_STREAM_PORT%"', launcher)
        self.assertIn("LIVE_CSV", launcher)
        self.assertIn("Get-NetTCPConnection", launcher)
        self.assertIn("REQUESTED_PORT", launcher)
        self.assertIn("REQUESTED_LIVE_STREAM_PORT", launcher)
        self.assertIn("/api/health", launcher)
        self.assertIn("auto_titration_dashboard", launcher)
        self.assertIn("OPEN_BROWSER", launcher)

    def test_dashboard_launcher_starts_web_server_before_collector(self):
        launcher = Path("launchers/windows/21_open_dashboard_server.bat").read_text(encoding="utf-8")

        self.assertIn("AUTO_COLLECT", launcher)
        self.assertIn("20_windows_live_collect.bat", launcher)
        self.assertIn("OUTPUT=%LIVE_CSV%", launcher)
        self.assertIn("VISIBLE_ROI_DETECTOR=yolo", launcher)
        self.assertIn("AUTO_INSTALL_YOLO=0", launcher)
        self.assertIn("AUTO_FRAMES", launcher)
        self.assertIn("999999", launcher)
        self.assertIn("CLEAN_OLD", launcher)
        self.assertIn("Stop-Process", launcher)
        self.assertIn("tools\\\\dashboard_server.py", launcher)
        self.assertNotIn("tools\\\\windows_live_collect.py|20_windows_live_collect.bat", launcher)
        self.assertIn("$_.ProcessId -ne $PID", launcher)
        self.assertIn("Waiting for app server", launcher)
        self.assertIn("Waiting for collector stream", launcher)
        self.assertIn("/api/collector-health", launcher)
        self.assertIn("Collector stream is ready", launcher)
        self.assertIn("Invoke-WebRequest", launcher)
        self.assertNotIn("/min", launcher)
        self.assertLess(
            launcher.index('start "Auto Titration App Server"'),
            launcher.index('start "Auto Titration Collector"'),
        )

    def test_dashboard_server_creates_live_preview_placeholders(self):
        with tempfile.TemporaryDirectory() as tmp:
            website_dir = Path(tmp) / "website"
            ensure_live_preview_placeholders(website_dir)

            visible = website_dir / "live" / "visible.bmp"
            thermal_bmp = website_dir / "live" / "thermal.bmp"
            thermal = website_dir / "live" / "thermal.json"
            self.assertTrue(visible.is_file())
            self.assertTrue(thermal_bmp.is_file())
            self.assertEqual(visible.read_bytes()[:2], b"BM")
            self.assertEqual(thermal_bmp.read_bytes()[:2], b"BM")
            payload = json.loads(thermal.read_text(encoding="utf-8"))
            self.assertIsNone(payload["temperature_avg_c"])
            self.assertEqual(payload["sync_quality"], "waiting")
            self.assertIsNone(payload["raw_avg"])

    def test_dashboard_health_identifies_the_service(self):
        dashboard = build_server("127.0.0.1", 0)
        thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
        thread.start()
        try:
            payload = json.loads(
                urlopen(
                    f"http://127.0.0.1:{dashboard.server_address[1]}/api/health",
                    timeout=5,
                ).read().decode("utf-8")
            )
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["service"], "auto_titration_dashboard")
            self.assertEqual(payload["version"], 1)
            self.assertTrue(payload["website_dir"].endswith("website"))
        finally:
            dashboard.shutdown()
            dashboard.server_close()
            thread.join(timeout=5)

    def test_dashboard_proxies_live_collector_api_and_streams(self):
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeLiveCollectorHandler)
        fake_thread = threading.Thread(target=fake.serve_forever, daemon=True)
        fake_thread.start()
        dashboard = build_server(
            "127.0.0.1",
            0,
            live_stream_base=f"http://127.0.0.1:{fake.server_address[1]}",
        )
        dashboard_thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
        dashboard_thread.start()
        base = f"http://127.0.0.1:{dashboard.server_address[1]}"
        try:
            settings = json.loads(urlopen(f"{base}/api/settings", timeout=5).read().decode("utf-8"))
            self.assertTrue(settings["ok"])
            health = json.loads(urlopen(f"{base}/api/collector-health", timeout=5).read().decode("utf-8"))
            self.assertTrue(health["collector_running"])
            self.assertTrue(health["visible_stream_ready"])
            started = time.perf_counter()
            with urlopen(f"{base}/stream/visible.mjpg", timeout=5) as response:
                first = response.read(len(b"--autotitrationframe\r\n"))
                first_elapsed = time.perf_counter() - started
                stream = first + response.read()
            self.assertLess(first_elapsed, 0.15)
            self.assertIn(b"JPEG", stream)
            request = Request(
                f"{base}/api/roi-click",
                data=json.dumps({"target": "visible", "x": 10, "y": 20}).encode("utf-8"),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            clicked = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
            self.assertEqual(clicked["path"], "/api/roi-click")
            self.assertEqual(clicked["payload"]["target"], "visible")
            self.assertEqual(clicked["payload"]["x"], 10)
            mobile = json.loads(urlopen(f"{base}/api/mobile/status", timeout=5).read().decode("utf-8"))
            self.assertEqual(mobile["mobile"]["source"], "android_mobile")
            for api_path, payload in [
                ("/api/roi-rect", {"target": "visible", "x": 1, "y": 2, "width": 3, "height": 4}),
                (
                    "/api/roi-polygon",
                    {
                        "target": "visible",
                        "frame_width": 12,
                        "frame_height": 12,
                        "points": [{"x": 2, "y": 2}, {"x": 8, "y": 2}, {"x": 8, "y": 8}],
                    },
                ),
                ("/api/roi-lock", {}),
                ("/api/roi-auto-candidate", {"target": "both"}),
                ("/api/mobile/pair", {}),
                ("/api/mobile/ingest", {"token": "abc", "frame": {"schema_version": "mobile_feature_frame.v1"}}),
                ("/api/pump/dispense", {}),
                ("/api/pump/retract", {}),
                ("/api/pump/stop", {}),
                ("/api/pump/reset", {}),
                ("/api/chemistry/constants/lookup", {"query": "acetic acid"}),
            ]:
                request = Request(
                    f"{base}{api_path}",
                    data=json.dumps(payload).encode("utf-8"),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                proxied = json.loads(urlopen(request, timeout=5).read().decode("utf-8"))
                self.assertEqual(proxied["path"], api_path)
        finally:
            dashboard.shutdown()
            dashboard.server_close()
            fake.shutdown()
            fake.server_close()

    def test_dashboard_served_index_forces_same_origin_collector_proxy(self):
        dashboard = build_server("127.0.0.1", 0)
        dashboard_thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
        dashboard_thread.start()
        base = f"http://127.0.0.1:{dashboard.server_address[1]}"
        try:
            html = urlopen(f"{base}/", timeout=5).read().decode("utf-8")
            self.assertIn("window.AUTO_TITRATION_STREAM_BASE = '.'", html)
            self.assertLess(html.index("AUTO_TITRATION_STREAM_BASE"), html.index('src="app.js"'))
        finally:
            dashboard.shutdown()
            dashboard.server_close()

    def test_dashboard_rejects_cross_origin_mutation_posts_when_lan_exposed(self):
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeLiveCollectorHandler)
        fake_thread = threading.Thread(target=fake.serve_forever, daemon=True)
        fake_thread.start()
        dashboard = build_server(
            "127.0.0.1",
            0,
            live_stream_base=f"http://127.0.0.1:{fake.server_address[1]}",
        )
        dashboard_thread = threading.Thread(target=dashboard.serve_forever, daemon=True)
        dashboard_thread.start()
        base = f"http://127.0.0.1:{dashboard.server_address[1]}"
        try:
            blocked = Request(
                f"{base}/api/roi-lock",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(blocked, timeout=5)
            self.assertEqual(ctx.exception.code, 403)

            wrong_scheme = Request(
                f"{base}/api/roi-lock",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json", "Origin": base.replace("http://", "https://")},
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(wrong_scheme, timeout=5)
            self.assertEqual(ctx.exception.code, 403)

            allowed = Request(
                f"{base}/api/roi-lock",
                data=b"{}",
                method="POST",
                headers={"Content-Type": "application/json", "Origin": base},
            )
            payload = json.loads(urlopen(allowed, timeout=5).read().decode("utf-8"))
            self.assertEqual(payload["path"], "/api/roi-lock")
        finally:
            dashboard.shutdown()
            dashboard.server_close()
            fake.shutdown()
            fake.server_close()


if __name__ == "__main__":
    unittest.main()
