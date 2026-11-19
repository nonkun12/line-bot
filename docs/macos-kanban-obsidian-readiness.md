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

## Uninstall

    launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.line-ai-secretary.kanban-obsidian-readiness.plist"
    rm "$HOME/Library/LaunchAgents/com.line-ai-secretary.kanban-obsidian-readiness.plist"

Uninstalling removes only this audit LaunchAgent. It does not remove the Obsidian save approval agent or any project data.
