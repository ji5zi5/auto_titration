"""Hardware-free regression checks for browser view navigation."""
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is required for browser navigation tests")
class ViewNavigationTests(unittest.TestCase):
    def test_full_compact_navigation_preserves_context_and_excludes_native(self):
        subprocess.run(["node", "tests/js/test_view_navigation.js"], check=True)

    def test_full_remote_view_keeps_server_settings_and_stop_priority(self):
        subprocess.run(["node", "tests/js/test_full_remote_control.js"], check=True)

    def test_roi_reset_requires_collector_confirmation_and_idle_capture(self):
        subprocess.run(["node", "tests/js/test_roi_reset.js"], check=True)
