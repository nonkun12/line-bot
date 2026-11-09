# GitHub App authentication migration

This repository is migrating workflow-created branches and pull requests from the
default `GITHUB_TOKEN` identity to short-lived, repository-scoped GitHub App
installation tokens.

## What this change covers

The staged token action is wired into:

- `.github/workflows/register-autonomous-task.yml`
- `.github/workflows/register-approved-autonomous-task.yml`
- `.github/workflows/line-development.yml`

Until the App credentials are configured, these workflows retain the existing
`GITHUB_TOKEN` fallback so the migration PR can be tested without breaking
current operations. If only one App secret is configured, the workflow fails
closed. Set the repository variable `GH_APP_AUTH_REQUIRED=true` after the
App path has been verified to prevent fallback.

## One-time GitHub App setup

1. Open **Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Give the App a clear name, for example `line-bot-automation`.
3. Under repository permissions, grant:
   - **Contents: Read and write**
   - **Pull requests: Read and write**
   - **Issues: Read-only** for the three workflows in this first migration slice.
   - **Metadata: Read-only** (required by GitHub).
4. Install the App on **Only select repositories** and select only
   `nonkun12/line-bot`.
5. Generate a private key for the App. Store the downloaded PEM securely.
6. In **nonkun12/line-bot → Settings → Secrets and variables → Actions → Secrets**,
   add:
   - `GH_APP_ID`: the numeric App ID (not the client ID).
   - `GH_APP_PRIVATE_KEY`: the complete PEM private-key contents.
7. Run a controlled task-registration or LINE-development workflow and verify
   that the workflow-created PR is authored by the new App installation.
8. After verification, add the repository Actions variable
   `GH_APP_AUTH_REQUIRED=true`. This makes missing App credentials a hard
   failure rather than silently reverting to `GITHUB_TOKEN`.

## Security and rollout notes

- The token is minted per workflow run by
  `actions/create-github-app-token@v2`; it expires automatically.
- The composite action requests only the permissions passed by each caller.
- The installation is restricted to this repository; do not install the App
  across all repositories.
- Never commit the PEM file or paste it into chat, issues, PRs, or workflow logs.
- This first slice fixes the task-registration and LINE-development PR paths.
  Other workflows that publish branches, create PRs, or dispatch workflows
  should be migrated in a separate reviewed pass with only their required
  permissions (for example, Actions write only where workflow dispatch is used).
