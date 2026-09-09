"""Continuous overnight job runner.

Keeps the existing one-step worker small and makes the execution loop explicit:
recover stale leases, execute one job step, then continue until stopped.  The
loop is safe to run as a single long-lived process because job claiming is
lease-based in the shared SQLite Job DB.
"""

from __future__ import annotations

import logging
import os
import signal
import time

import db
import job_worker

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = float(os.environ.get("JOB_WORKER_POLL_INTERVAL_SECONDS", "5"))
MAX_CYCLES = int(os.environ.get("JOB_WORKER_MAX_CYCLES", "0"))
IDLE_BACKOFF_MAX_SECONDS = float(os.environ.get("JOB_WORKER_IDLE_BACKOFF_MAX_SECONDS", "30"))

_STOP = False


def _stop(_signum, _frame):
    global _STOP
    _STOP = True
    logger.info("overnight worker stopping")


def install_signal_handlers() -> None:
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _stop)


def run_forever(*, run_once=job_worker.run_once, sleep=time.sleep) -> int:
    """Run jobs continuously until stopped or MAX_CYCLES is reached.

    A cycle is one call to ``run_once``.  Empty queues use bounded backoff so
    the worker does not busy-loop, while a completed/failed/waiting job resets
    the delay immediately.  ``run_once`` owns lease acquisition and recovery;
    this runner deliberately does not duplicate that state-management logic.
    """
    global _STOP
    _STOP = False
    db.init_db()
    install_signal_handlers()

    cycles = 0
    idle_delay = max(0.0, POLL_INTERVAL_SECONDS)
    while not _STOP:
        if MAX_CYCLES and cycles >= MAX_CYCLES:
            break
        cycles += 1
        try:
            result = run_once()
            if result is None:
                sleep(idle_delay)
                idle_delay = min(
                    IDLE_BACKOFF_MAX_SECONDS,
                    max(POLL_INTERVAL_SECONDS, idle_delay * 2),
                )
            else:
                idle_delay = max(0.0, POLL_INTERVAL_SECONDS)
                logger.info(
                    "job cycle complete: job_id=%s status=%s",
                    result.get("id"), result.get("status"),
                )
        except Exception:
            logger.exception("overnight worker cycle failed")
            sleep(idle_delay)
            idle_delay = min(
                IDLE_BACKOFF_MAX_SECONDS,
                max(POLL_INTERVAL_SECONDS, idle_delay * 2),
            )

    return cycles


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    run_forever()
