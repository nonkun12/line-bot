# Obsidian Production Integration

The Obsidian agent is a bounded local knowledge-store integration.

## Supported operations

Obsidianに保存 notes/example.md: 内容
Obsidianに追記 notes/example.md: 内容
Obsidianを読む notes/example.md
Obsidianで検索 キーワード
Obsidian一覧

## Safety boundary

- OBSIDIAN_VAULT_PATH must explicitly point to an existing directory.
- Only .md files are accessible.
- Absolute paths, .. traversal, and resolved symlink escapes are rejected.
- Create/save will not overwrite an existing note; overwrite requires explicit append mode.
- Writes are capped at 20,000 characters per request.
- Reads are capped at 20,000 returned characters.
- Search results are bounded to 20 notes; list results to 200 notes.
- Obsidian requests are explicitly routed and do not fall through to the general AI.
- Read and write capabilities are checked separately through the specialist gate.
- The integration performs no network calls, command execution, deploys, merges, or permission changes.

## Deployment boundary

The vault is a local filesystem. A cloud-hosted Render process cannot access a Mac-local vault path.

For LINE-to-Mac Obsidian operation, the next production deployment step is a local Mac bridge running only while the Mac is online. The bridge should authenticate requests, accept only the same bounded operations, and never expose the vault directly to the public network.