# Goal-driven autonomous runtime integration

The Goal policy engine selects one bounded next task from the versioned runtime queue. The bridge admits only tasks whose exact ID, instruction, and allowed paths match the registered catalog and whose catalog entry has execution_approved=true.

Each selected task is handed to the existing minimal autonomous runner. That runner remains authoritative for Control Tower selection, repository HEAD checks, Recovery AI HOLD checks, REA preflight, guarded execution, post-generation REA, Recovery AI persistence, and orchestration. The bridge independently checks runner evidence and the publish gate before marking a task complete.

The SQLite store provides revisioned compare-and-swap state and atomic single-task claims during a workflow run. A completed goal snapshot is exported only after every selected task passes the existing publish gate; the workflow then stores it in the autonomous-loop-state branch and verifies durable read-back. Failed, ambiguous, stopped, or unverified tasks are held and are not silently retried.

A held task can return to PENDING only through the existing explicit resume path after cause-fixed and post-resume-review confirmations. An IN_PROGRESS task is never reset automatically.

## Safety boundary

- No merge, deployment, permission change, secret change, or production write is enabled.
- Only exact catalog-approved tasks enter the bridge; runtime queue contents alone do not grant authority.
- Existing STOP, HOLD, REA, Recovery AI, and independent publish checks remain in force.
- The bridge is used for normal development tasks; the separately allowlisted incident workflow continues through its existing guarded runner.
- Scheduled GitHub Actions are best-effort and do not guarantee 24/7 uptime. Local-only models cannot run while the Mac is off.
