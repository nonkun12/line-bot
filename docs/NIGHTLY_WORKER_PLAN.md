# Nightly Autonomous Worker

## Current phase

The nightly worker is deliberately conservative. It runs the existing smoke test and the full pytest suite and reports the result. It does not modify source, commit, or deploy.

## Target phase

1. Select a bounded development task from an explicit task queue.
2. Ask the implementation agent to work only on allowed files.
3. Run pytest.
4. On failure, invoke Debug/Fix/Patch agents.
5. Re-run tests with a bounded retry count.
6. Produce a reviewable diff.
7. Commit only validated target files.
8. Deploy only through an explicit deployment workflow.
9. Run E2E verification.
10. Publish a morning report.

No autonomous production deployment should be enabled until each stage has its own tests and rollback/stop conditions.
