import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.watch_distributed_loop_safety import check_once

class WatcherTests(unittest.TestCase):
    def test_all_clear(self):
        with patch("scripts.watch_distributed_loop_safety.check_remote_stop"):
            with patch("scripts.watch_distributed_loop_safety.check_global_hold"):
                with patch("scripts.watch_distributed_loop_safety.check_budget"):
                    with tempfile.TemporaryDirectory() as tmp:
                        stop = Path(tmp) / "stop"
                        self.assertTrue(check_once(stop))
                        self.assertFalse(stop.exists())

    def test_failure_creates_stop_file(self):
        with patch("scripts.watch_distributed_loop_safety.check_remote_stop"):
            with patch("scripts.watch_distributed_loop_safety.check_global_hold", side_effect=RuntimeError("unknown")):
                with tempfile.TemporaryDirectory() as tmp:
                    stop = Path(tmp) / "stop"
                    self.assertFalse(check_once(stop))
                    self.assertTrue(stop.exists())

if __name__ == "__main__":
    unittest.main()
