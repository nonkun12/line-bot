"""Reproducible parity test for the selector stage only.

Python remains authoritative for validation, approval, HOLD/review/completion
eligibility, and priority-score calculation. This test compares ordering and
bounded selection after those inputs have already been computed.
"""
from __future__ import annotations

import random
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rust" / "task-selector" / "Cargo.toml"
BINARY = ROOT / "rust" / "task-selector" / "target" / "debug" / "orca-task-selector"


def python_reference(rows: list[tuple[str, int, int, bool]], limit: int) -> list[str]:
    eligible = [(index, row) for index, row in enumerate(rows) if row[3]]
    eligible.sort(key=lambda item: (-item[1][1], item[1][2], item[0]))
    return [row[0] for _, row in eligible[:limit]]


class RustSelectorShadowParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(
            ["cargo", "build", "--manifest-path", str(MANIFEST), "--bin", "orca-task-selector"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def assert_parity(self, rows: list[tuple[str, int, int, bool]], limit: int) -> None:
        payload = "".join(
            f"{task_id}\\t{score}\\t{order}\\t{str(eligible).lower()}\\n"
            for task_id, score, order, eligible in rows
        )
        result = subprocess.run(
            [str(BINARY), str(limit)],
            input=payload,
            capture_output=True,
            text=True,
            check=True,
        )
        rust_ids = result.stdout.splitlines()
        self.assertEqual(rust_ids, python_reference(rows, limit))

    def test_ties_eligibility_and_limits(self) -> None:
        rows = [
            ("task-held", 99, 0, False),
            ("task-c", 5, 2, True),
            ("task-a", 5, 0, True),
            ("task-b", 5, 1, True),
            ("task-low", -2, 3, True),
        ]
        for limit in range(1, 5):
            with self.subTest(limit=limit):
                self.assert_parity(rows, limit)

    def test_deterministic_generated_cases(self) -> None:
        rng = random.Random(20261114)
        for case in range(120):
            count = rng.randint(1, 35)
            rows = [
                (f"task-{case:03d}-{index:03d}", rng.randint(-10, 20),
                 rng.randint(0, 12), rng.choice((True, False)))
                for index in range(count)
            ]
            limit = rng.randint(1, 4)
            with self.subTest(case=case, limit=limit):
                self.assert_parity(rows, limit)


if __name__ == "__main__":
    unittest.main()
