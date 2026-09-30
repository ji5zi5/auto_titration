import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.request

from tools.windows_live_collect import (
    LiveCsvBuffer,
    LiveStreamState,
    start_live_stream_server,
)


class RemoteConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config_path = self.root / "remote-config.json"
        self.commands = []
        self.handles = []

    def tearDown(self):
        for handle in reversed(self.handles):
            handle.close()

    def _start(self, *, csv_buffer=None):
        handle = start_live_stream_server(
            "127.0.0.1",
            0,
            LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=self.commands.append,
            remote_config_path=self.config_path,
        )
        self.handles.append(handle)
        return "http://127.0.0.1:%s/api/remote/config" % handle.server.server_address[1]

    @staticmethod
    def _config():
        return {
            "pump_rate_ml_per_s": 0.99,
            "titration_type": "weak_acid_strong_base",
            "sample_volume_ml": 20,
            "auto_stop_enabled": True,
        }

    @staticmethod
    def _get(url):
        return json.load(urllib.request.urlopen(url, timeout=2))

    @staticmethod
    def _post(url, body):
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return json.load(urllib.request.urlopen(request, timeout=2))

    def test_shared_config_survives_collector_restart_without_moving_pump(self):
        first_url = self._start()
        initial = self._get(first_url)
        self.assertIsNone(initial["config"])
        self.assertTrue(initial["defaults_allowed"])
        body = self._config()

        self.assertTrue(self._post(first_url, body)["ok"])
        self.assertEqual(self._get(first_url)["config"], body)
        self.handles.pop().close()

        second_url = self._start()
        self.assertEqual(self._get(second_url)["config"], body)
        self.assertEqual(self.commands, [])

    def test_clear_is_persistent_and_does_not_move_pump(self):
        url = self._start()
        self._post(url, self._config())
        self.assertTrue(self._post(url, {"clear": True})["ok"])
        cleared = self._get(url)
        self.assertIsNone(cleared["config"])
        self.assertFalse(cleared["defaults_allowed"])
        self.handles.pop().close()

        restarted_url = self._start()
        restored = self._get(restarted_url)
        self.assertIsNone(restored["config"])
        self.assertFalse(restored["defaults_allowed"])
        self.assertEqual(self.commands, [])

    def test_invalid_or_corrupt_saved_config_fails_closed(self):
        invalid_values = [
            "{not-json",
            json.dumps({"pump_rate_ml_per_s": 0}),
            json.dumps([self._config()]),
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                if self.handles:
                    self.handles.pop().close()
                self.config_path.write_text(value, encoding="utf-8")
                url = self._start()
                response = self._get(url)
                self.assertIsNone(response["config"])
                self.assertFalse(response["defaults_allowed"])
        self.assertEqual(self.commands, [])

    def test_invalid_post_preserves_saved_config(self):
        url = self._start()
        body = self._config()
        self._post(url, body)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post(url, {"pump_rate_ml_per_s": 0})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self._get(url)["config"], body)
        self.handles.pop().close()
        self.assertEqual(self._get(self._start())["config"], body)

    def test_failed_atomic_persistence_does_not_accept_mutation(self):
        url = self._start()
        original = self._config()
        replacement = {**original, "sample_volume_ml": 30}
        self._post(url, original)

        with mock.patch(
            "tools.windows_live_collect.os.replace",
            side_effect=OSError("disk unavailable"),
        ):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self._post(url, replacement)
        self.assertEqual(caught.exception.code, 500)
        self.assertEqual(self._get(url)["config"], original)
        self.handles.pop().close()
        self.assertEqual(self._get(self._start())["config"], original)

    def test_config_and_clear_are_rejected_while_recording(self):
        csv_buffer = LiveCsvBuffer(output_path=self.root / "recording.csv")
        url = self._start(csv_buffer=csv_buffer)
        original = self._config()
        self._post(url, original)
        csv_buffer.start_recording()

        for mutation in ({"clear": True}, {**original, "sample_volume_ml": 30}):
            with self.subTest(mutation=mutation):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self._post(url, mutation)
                self.assertEqual(caught.exception.code, 409)
                self.assertEqual(self._get(url)["config"], original)
        csv_buffer.request_stop()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post(url, {"clear": True})
        self.assertEqual(caught.exception.code, 409)
        self.assertEqual(self._get(url)["config"], original)
        self.assertEqual(self.commands, [])

if __name__ == "__main__":
    unittest.main()
