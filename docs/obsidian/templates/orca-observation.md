---
type: orca-observation
id: ORCA-YYYYMMDD-<stream-key>-<evidence-id>
status: UNKNOWN
repo: nonkun12/line-bot
stream_key: ""
source: legacy_unverified
observation_type: unverified
captured_at: ""
target_sha: ""
run_id: ""
evidence_digest: ""
freshness: UNKNOWN
tags:
  - orca
  - runtime-evidence
---

# <Stream label> — <capture time>

## Status

UNKNOWN

## Evidence classification

- Source:
- Observation type:
- Stream key:
- Captured at:
- Target SHA:
- Workflow/collector run ID:
- Evidence digest:
- Freshness:

## Observed facts

- <Only facts supported by the cited evidence>

## Reported but not independently verified

- <Workflow self-report or sender-supplied claims>

## Missing evidence / unchecked items

- [ ] <Missing run verification, worker identity, task link, etc.>

## Related records

- GitHub run:
- Commit:
- REA scan:
- Related Obsidian note:

## Decision / follow-up

- [ ] <Next safe action>

## Provenance boundary

`orca_collector/runtime_observation` may represent a collector observation. `github_actions/workflow_execution` is a workflow self-report and must remain `reported` until independently verified against GitHub Actions. `legacy_unverified/unverified` must remain UNKNOWN. This note grants no execution or deployment authority.
