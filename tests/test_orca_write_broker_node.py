"""Run the Durable Object's native Node concurrency contract tests in pytest CI."""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import unittest

TEST_FILE = pathlib.Path(__file__).parent.parent / "cloudflare/orca-test-api/tests/write-broker.test.mjs"


@unittest.skipUnless(shutil.which("node"), "Node.js is required for Durable Object tests")
class WriteBrokerNodeTests(unittest.TestCase):
    def test_serialized_write_broker_contract(self):
        result = subprocess.run(
            ["node", "--test", str(TEST_FILE)],
            text=True,
            capture_output=True,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
