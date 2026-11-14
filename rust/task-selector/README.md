# Orca Rust Task Selector (shadow phase)

This is the first isolated Rust component for the distributed development loop.

## Scope

- Deterministic ranking of already-validated, eligible task additions.
- Matches the ordering stage in `scripts/autonomous_task_refill.py`: descending history priority score, then reviewed catalog order.
- Python remains responsible for catalog/schema validation, history parsing and score calculation, eligibility (approval/HOLD/review/completed/already-queued exclusions), and retaining eligible existing queue entries.
- Bounded result count and fail-closed duplicate/blank ID validation.
- No dependencies outside the Rust standard library.

## Deliberate non-goals

This crate does not read or write queue/state files, create approvals, clear Global HOLD, change Emergency Stop, claim leases, invoke subprocesses, call GitHub, generate code, merge, or deploy. It is not connected to production execution in this phase.

## Test

Run `cargo test --manifest-path rust/task-selector/Cargo.toml`.

The first integration step should run this selector in shadow mode against the same Python-validated candidate additions and compare ordered task IDs. Python remains authoritative until parity, fail-closed behavior, and performance are measured. Do not enable Rust as the execution authority based only on these unit tests.
