"""Read-only upstream response simulation: no real collector or pump requests."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from tools import dashboard_server as dashboard


class ProxyErrorTests(unittest.TestCase):
    def handler(self):
        return SimpleNamespace(
            config=SimpleNamespace(live_stream_base="http://127.0.0.1:8766"),
            path="/api/csv/start", headers={"Content-Length": "2"},
            rfile=io.BytesIO(b"{}"), wfile=io.BytesIO(),
            send_response=Mock(), send_header=Mock(), end_headers=Mock(),
            _send_dashboard_cors_headers=Mock(),
        )

    def test_upstream_error_preserves_status_json_and_diagnostics(self):
        for status in (400, 409, 503):
            with self.subTest(status=status):
                body = json.dumps({"ok": False, "error": "초기색 보정 실패",
                                   "auto_stop": {"auto_stop_state": "error"}}).encode()
                error = HTTPError("http://localhost/api/csv/start", status,
                                  "rejected", {"Content-Type": "application/json"},
                                  io.BytesIO(body))
                handler = self.handler()
                with patch.object(dashboard, "urlopen", side_effect=error):
                    dashboard.DashboardHandler._proxy_to_live_collector(handler, "POST")
                handler.send_response.assert_called_once_with(status)
                self.assertEqual(handler.wfile.getvalue(), body)

    def test_transport_failure_remains_gateway_error_without_retry(self):
        handler = self.handler()
        with patch.object(dashboard, "urlopen", side_effect=URLError("unreachable")) as call:
            dashboard.DashboardHandler._proxy_to_live_collector(handler, "POST")
        self.assertEqual(call.call_count, 1)
        handler.send_response.assert_called_once_with(502)
        self.assertFalse(json.loads(handler.wfile.getvalue())["ok"])
        self.assertEqual(json.loads(handler.wfile.getvalue())["request_outcome"], "unknown")


if __name__ == "__main__":
    unittest.main()
