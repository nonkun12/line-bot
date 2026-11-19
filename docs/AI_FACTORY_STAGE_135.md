# Stage 135: disposable runtime sandbox

Stage 135 adds a Docker-backed unittest gate for generated agent candidates.

- Requires an immutable SHA-256-pinned container image.
- Executes tests only inside Docker, never imports generated code on the host.
- Disables network, uses a read-only root and read-only artifact mount, drops
  Linux capabilities, enables no-new-privileges, and applies memory/CPU/PID
  limits plus a bounded timeout.
- Uses an unprivileged container user and a bounded temporary filesystem.
- Zero discovered tests, timeouts, missing Docker, nonzero exits, invalid paths,
  and infrastructure errors all fail closed.
- Generated files are staged only in a temporary directory and removed when
  the run exits.

Trust boundary: Docker daemon, container runtime, host kernel, and pinned image.
This is stronger than static inspection but is not a formal proof against
container-runtime or kernel vulnerabilities. No network access is granted.
