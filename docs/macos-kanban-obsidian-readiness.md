# macOS local Kanban + Obsidian readiness audit

This adds a small login-time audit for the local Mac workflow. It complements the separate Obsidian approval prompt; it does not replace that prompt.

## Behaviour

- Runs once at the current user's macOS login through a LaunchAgent (RunAtLoad=true, KeepAlive=false).
- Checks the local ~/line-bot and ~/hermes-local/hermes-agent Git working trees without changing them.
- Opens the existing Kanban SQLite database in read-only mode, runs PRAGMA quick_check, and reports task counts by status without exposing task titles.
- Verifies that the Obsidian bridge scripts, config keys, vault directory, and existing login-approval agent are present.
- Accepts an HTTPS server URL (or loopback HTTP for local testing). It does not call the URL or make any network request.
- Writes a JSONL history and a latest JSON report under ~/.local/state/line-ai-secretary/, outside both repositories. The log directory is private (0700) and reports are best-effort (0600).
- Never prints or writes bridge-key values. Dirty Git trees are reported as warnings and are left untouched. Any failed prerequisite gives a non-zero exit status.

## Install once

From the ~/line-bot repository root:

    zsh scripts/install_macos_kanban_obsidian_readiness.sh

The installer writes and loads one per-user LaunchAgent, then runs one read-only audit immediately. No polling, paid service, hosted model, commit, merge, deploy, or worker start is involved.

## Inspect the latest local result

Open:

    ~/.local/state/line-ai-secretary/kanban-obsidian-readiness-latest.json

The same results are appended to:

    ~/.local/state/line-ai-secretary/kanban-obsidian-readiness.jsonl

The report is a readiness check, not proof that an Obsidian save has succeeded. The end-to-end save path still requires one real Mac test: LINE queue creation, login prompt, explicit 実行, one-shot bridge claim, saved note read-back, and bridge exit. A missing/unavailable local Mac cannot be verified from GitHub.

## Kanban → Obsidian integration contract (next phase)

This section defines the hand-off that the next implementation must obey. Adding this contract does not claim that the end-to-end integration has already been tested.

### Status meanings

- `TODO`: accepted task, not started.
- `IN PROGRESS`: one local worker has claimed the task.
- `REVIEW`: implementation finished; tests and the Safety Gate still need to pass.
- `DONE`: implementation and required checks passed. This does **not** mean an Obsidian note was saved.
- `BLOCKED`: missing approval/configuration, failed validation, exhausted bounded repair, or any ambiguous state. Never convert a failure into `DONE`.

A task may move to `DONE` only with concrete test/verification evidence. A queued dispatch, successful HTTP response, or empty queue is not task-completion evidence.

### Safe hand-off sequence

1. A request creates a bounded Kanban task. The task has a stable ID, status, creation time, and a short result/evidence reference; credentials and full private note contents do not belong in status logs.
2. A Mac-local worker claims one task atomically. If the Mac is offline, the task remains pending. A stale `IN PROGRESS` task may return to pending only under the existing bounded recovery policy; it must never be marked complete automatically.
3. The worker runs the task in the allowlisted workspace. External access is denied by default; any required network/provider access must be explicitly allowed for that task. No paid API/provider is introduced by this integration.
4. The result enters `REVIEW`. Tests, changed-file scope, and the Safety Gate must pass before `DONE`; otherwise use `BLOCKED` and record a sanitized reason.
5. Obsidian persistence is a separate downstream action, not an automatic side effect of marking a task `DONE`. The user must explicitly request the save and approve `実行` in the Mac login prompt. `後で` leaves the job pending and does not run the bridge.
6. The Mac bridge runs once, claims only the approved job, writes only through the configured vault path and allowed append/save command, reads the saved content back, reports the result, and exits. Do not enable continuous polling for this flow.
7. If saving or read-back fails, report failure and keep the result non-successful. Do not retry writes indefinitely, overwrite existing notes, delete files, bulk-move notes, or auto-merge/auto-deploy.

### Mac acceptance checklist

- [ ] A task created while the Mac is offline remains pending and is not claimed by a cloud worker.
- [ ] Login presents the approval prompt when a pending Obsidian save exists.
- [ ] Choosing `後で` leaves the job pending and suppresses repeated prompts for the configured cooldown.
- [ ] Choosing `実行` runs one bridge process for the approved job only.
- [ ] The bridge uses the configured vault and HTTPS/loopback URL policy; no secret value is printed to logs.
- [ ] The saved note is read back and verified before success is reported.
- [ ] The bridge exits after the one-shot job; no polling worker remains active.
- [ ] Failed validation or ambiguous status becomes `BLOCKED`, never `DONE`.
- [ ] Git working trees and pre-existing vault notes are preserved; no automatic merge, deploy, delete, overwrite, or bulk move occurs.

Until this checklist is run on the actual Mac, the workflow is **not end-to-end verified**. The readiness audit is only a local preflight.

## Uninstall

    launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.line-ai-secretary.kanban-obsidian-readiness.plist"
    rm "$HOME/Library/LaunchAgents/com.line-ai-secretary.kanban-obsidian-readiness.plist"

Uninstalling removes only this audit LaunchAgent. It does not remove the Obsidian save approval agent or any project data.
