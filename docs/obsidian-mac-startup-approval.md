# Obsidian Mac startup approval

LINE creates a save request. At Mac login, the checker makes exactly one non-claiming pending check.
If a request exists, macOS asks for 後で / 実行. Only 実行 starts the one-shot bridge.
The bridge claims at most one job and exits. Obsidian is opened and left running.
There is no polling and no KeepAlive.

Install from the repository root:

    zsh scripts/install_obsidian_startup.sh
