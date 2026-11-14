"""Informational end-to-end selector benchmark: Python sort vs Rust subprocess bridge.

Measures only the already-validated selector stage. Rust timing includes payload
serialization, process startup, input parsing/ID validation, sorting, and output
parsing. Python timing includes equivalent selection and result-list creation.
No production code is imported or changed; results are runner-specific.
"""
from __future__ import annotations

import json
import random
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "rust" / "task-selector" / "target" / "release" / "orca-task-selector"
SIZES = (10, 100, 1_000, 10_000)
REPEATS = 21
LIMIT = 4


def make_rows(count: int) -> list[tuple[str, int, int, bool]]:
    rng = random.Random(20261114 + count)
    return [
        (f"task-{index:08d}", rng.randint(-100, 100), index, rng.random() >= 0.2)
        for index in range(count)
    ]


def python_select(rows: list[tuple[str, int, int, bool]]) -> list[str]:
    eligible = [(index, row) for index, row in enumerate(rows) if row[3]]
    eligible.sort(key=lambda item: (-item[1][1], item[1][2], item[0]))
    return [row[0] for _, row in eligible[:LIMIT]]


def rust_bridge(rows: list[tuple[str, int, int, bool]]) -> list[str]:
    payload = "".join(
        f"{task_id}\t{score}\t{order}\t{str(eligible).lower()}\n"
        for task_id, score, order, eligible in rows
    )
    result = subprocess.run(
        [str(BINARY), str(LIMIT)],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


def measure(fn, rows) -> list[int]:
    samples = []
    expected = python_select(rows)
    for _ in range(REPEATS):
        start = time.perf_counter_ns()
        actual = fn(rows)
        elapsed = time.perf_counter_ns() - start
        if actual != expected:
            raise AssertionError("Python/Rust selector result mismatch")
        samples.append(elapsed)
    return samples


def percentile95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.95 * (len(ordered) - 1)))]


def main() -> None:
    if not BINARY.is_file():
        raise SystemExit(f"missing release binary: {BINARY}")
    print("selector benchmark (informational; milliseconds; median of 21 runs)")
    print("candidates,python_median_ms,rust_bridge_median_ms,python_p95_ms,rust_bridge_p95_ms,bridge_over_python")
    for size in SIZES:
        rows = make_rows(size)
        py = measure(python_select, rows)
        rs = measure(rust_bridge, rows)
        py_med = statistics.median(py)
        rs_med = statistics.median(rs)
        ratio = rs_med / py_med if py_med else float("inf")
        print(
            f"{size},{py_med / 1e6:.4f},{rs_med / 1e6:.4f},"
            f"{percentile95(py) / 1e6:.4f},{percentile95(rs) / 1e6:.4f},{ratio:.2f}x"
        )


if __name__ == "__main__":
    main()
