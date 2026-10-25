"""Run Creator-Critic only when the distributed loop has actionable evidence.

The model output is an artifact for human review only. Actionable observations receive two bounded rounds so the Creator can address Critic feedback. This runner does not
change source code, queues, approval state, task state, or deployment state.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from scripts.creator_critic_loop_advisory import build_objective

DEPENDENCIES = (
    "llama-cpp-python==0.3.16",
    "huggingface-hub==0.35.3",
)


def run_advisory(
    results_path: str | Path,
    output_path: str | Path,
    *,
    runner_path: str | Path | None = None,
    python_executable: str = sys.executable,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run the pinned CPU inference runner only for an actionable result.

    `run` is injectable so tests can verify command selection and generate a
    fake transcript without installing packages or loading a model.
    """
    output = Path(output_path)
    # Do not upload a previous transcript when this run has no actionable event.
    output.unlink(missing_ok=True)

    objective = build_objective(results_path)
    if objective is None:
        print("CREATOR_CRITIC_ADVISORY=SKIP")
        return 0

    model_runner = Path(runner_path) if runner_path else Path(__file__).with_name("run_creator_critic_github.py")
    output.parent.mkdir(parents=True, exist_ok=True)

    install_env = os.environ.copy()
    # Match the known-working hosted runner build and avoid host-specific CPU flags
    # in the compiled llama.cpp extension.
    install_env["CMAKE_ARGS"] = "-DGGML_NATIVE=OFF"
    install = run(
        [python_executable, "-m", "pip", "install", "--disable-pip-version-check", *DEPENDENCIES],
        check=False,
        env=install_env,
    )
    if install.returncode != 0:
        print("CREATOR_CRITIC_HOLD: dependency installation failed", file=sys.stderr)
        return 2

    result = run(
        [
            python_executable,
            str(model_runner),
            "--rounds", "2",
            "--objective", objective,
            "--output", str(output),
        ],
        check=False,
    )
    if result.returncode != 0:
        print("CREATOR_CRITIC_HOLD: advisory inference failed", file=sys.stderr)
        return result.returncode
    print("CREATOR_CRITIC_ADVISORY=ARTIFACT_ONLY")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, help="Loop JSONL evidence path")
    parser.add_argument("--output", required=True, help="Transcript artifact path")
    args = parser.parse_args(argv)
    return run_advisory(args.results, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
