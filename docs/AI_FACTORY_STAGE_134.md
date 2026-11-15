# Stage 134: Builder artifact generation and static sandbox gate

Stage 134 adds a concrete local-model Builder and a non-executing static
inspection gate for generated Python artifacts.

## Builder
- Calls the injected Stage 132 Ollama loopback client; no remote fallback.
- Accepts strict JSON only, with bounded file count and per-file/total size.
- Requires paths under the existing AgentFactory roots and both source + test.
- Rejects malformed schema, traversal, duplicate paths, empty files, and
  unsupported output paths.
- Returns in-memory GeneratedFile objects only; no repository writes.

## Static sandbox gate
- Parses and compiles source text without importing or executing it.
- Rejects selected high-risk imports (network, subprocess, filesystem helpers)
  and dynamic/IO calls such as eval, exec, compile, __import__, open, input.
- Emits evidence and explicit failures for the existing AgentFactory gate.

## Important limitation
This is a static, non-executing safety gate, not an OS/container isolation
boundary and not execution of the generated test suite. A later stage must
connect a disposable sandbox runner with resource limits before claiming
runtime test coverage. Independent TEST and REVIEW evidence remain required.
No files are written by the builder; no permissions, catalog registration,
activation, scheduler, merge, or deployment are changed.
