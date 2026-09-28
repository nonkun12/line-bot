# UHIP Phase 0 Protocol

## Goal

Demonstrate that camera-based recognition can produce a stable, deterministic, non-actionable event stream locally.

## Pipeline

camera -> landmarks -> classifier -> Recognition Gate -> event draft -> statistics

## Required negative cases

- typing
- drinking/eating
- smartphone use
- ordinary conversation gestures
- grabbing objects
- low light
- out-of-frame hand
- multiple hands
- multiple people
- unstable tracking

## Acceptance criteria

- Negative corpus: zero false triggers in the validated corpus.
- Rule-of-three upper bound is recorded as 3/T, where T is total negative observation time.
- Deterministic replay produces identical gate decisions for identical input.
- Low confidence and ambiguous tracking never emit actionable events.
- p95 recognition-to-event latency is measured before enabling later phases.
- Raw camera frames are not written to the repository.
- Any opt-in trace data is ignored by git and has an explicit retention/deletion policy.

## Explicit non-goals

Phase 0 cannot control the desktop, send network requests, approve actions, or operate AI Secretary.
