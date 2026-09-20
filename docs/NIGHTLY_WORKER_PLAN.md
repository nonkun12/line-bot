# Daily Self-Improvement Worker

## Current phase

The daily worker uses the existing guarded autonomous path. It makes at most one bounded improvement attempt, runs pytest, and publishes changes only through a reviewable PR.

## Daily loop

1. Inspect the current repository state and existing test results.
2. Select one safe and testable improvement outside protected control-plane files.
3. Generate and validate one minimal patch, then run pytest.
4. Allow at most one bounded repair attempt.
5. Run a final read-only verification with autonomous autofix disabled.
6. Publish a dedicated branch and PR only when verification succeeds.



If no safe improvement is identified, stop without forcing a change.

Automatic merge and production deployment remain disabled. Persisted runtime signals and the distributed Manager -> Debugger -> Reviewer observer are the next integration step.
