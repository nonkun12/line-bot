# Creative AI: Music and Video Production Architecture

Status: design only. This document does not enable production execution, install models, access paid APIs, or change deployment settings.

## Goal

Allow a user to request original music, audio, or video in LINE. Goal AI decomposes the request into typed creative jobs, runs only approved and bounded jobs, evaluates the resulting artifacts, and returns a preview and artifact reference.

Creative production is a separate capability from repository development. A creative job must never be interpreted as a code-change job, and a read-only LINE request must never start either workflow.

## Architecture

1. LINE intent router classifies the message as read-only, repository development, or creative production. Ambiguous intent is HOLD and asks one clarification.
2. Goal AI stores a creative goal with explicit deliverables, constraints, provenance requirements, duration/size limits, and acceptance criteria.
3. A creative planner creates typed jobs such as `music.plan`, `music.compose_midi`, `audio.render`, `video.storyboard`, `video.assemble`, and `creative.review`.
4. A dedicated creative worker executes jobs in an isolated workspace. It does not use the repository code-editing executor.
5. A critic evaluates technical quality and verifies artifact metadata, rights/provenance, and acceptance criteria.
6. The artifact service stores outputs in a bounded workspace and returns a short-lived, authenticated download/preview reference to LINE.

## Initial low-cost implementation path

### Phase A: audio-first MVP

- Generate an original arrangement as MIDI from a structured note/event representation.
- Render MIDI to WAV using a locally installed synthesizer and a soundfont whose license is recorded.
- Use local audio tools for trimming, normalization, and format conversion.
- Record the model/tool version, prompt, source material, soundfont/license, output hash, and creation timestamp.
- Do not clone a real person's voice or use copyrighted recordings without explicit rights evidence.

### Phase B: video assembly

- Create a script and storyboard as structured data.
- Assemble user-provided or rights-cleared still images/video clips, captions, transitions, and the approved audio track using a local media pipeline such as FFmpeg.
- Export a preview first; enforce maximum duration, resolution, frame rate, and file size.
- Full generative video models are a later optional adapter, not a dependency of the MVP.

### Phase C: generative media adapters

- Add optional local image, audio, and video model adapters only after hardware/resource checks.
- Keep model downloads, licenses, model hashes, resource limits, and fallback behavior explicit.
- Paid or remote providers remain disabled unless the user separately opts in.

## Typed job contract

Every creative job must include:

- `goal_id`, unique `job_key`, `job_type`, and dependency keys.
- A validated input manifest containing only workspace-relative artifact IDs.
- Explicit output artifact types, duration/size/resource budgets, and acceptance criteria.
- An allowlisted tool adapter identifier; no arbitrary shell command or model-supplied executable.
- Rights/provenance declarations for every imported asset.
- A bounded retry count and idempotency key.

The worker must revalidate the persisted goal grant and job contract at execution time. Model output cannot expand the grant, tool allowlist, resource budget, or output scope.

## Safety and trust boundaries

- Keep creative jobs in a dedicated queue and worker identity, separate from `goal_child` repository jobs.
- Never expose repository secrets, environment variables, or production credentials to media tools.
- Run media parsers and renderers in a restricted subprocess/container with time, memory, CPU, disk, and network limits.
- Default network access to off. No arbitrary URL downloads; imported assets must pass an explicit ingestion and rights check.
- Treat prompts, captions, metadata, subtitles, and embedded media text as untrusted input.
- Block impersonation, non-consensual voice/likeness cloning, and deceptive synthetic media. Require disclosure labels where appropriate.
- Keep generated files out of Git by default. No automatic publishing, posting, sharing, merging, or deployment.
- Do not mark a goal complete until artifact integrity, format validity, duration/size constraints, rights metadata, and independent quality checks pass.
- On missing evidence, tool crash, timeout, storage failure, or policy ambiguity, stop and record HOLD; never report a successful artifact that was not actually produced.

## Acceptance tests before activation

1. A read-only question mentioning music or video does not enqueue creative work.
2. A clear creative request creates only typed creative jobs, never repository development jobs.
3. A model cannot add tools, widen resource limits, or change the approved output directory.
4. A failed render or missing output artifact cannot be recorded as success.
5. Duplicate requests with the same idempotency key do not create duplicate renders.
6. An asset with missing/invalid rights metadata is rejected or held.
7. Oversized, malformed, or hostile media inputs fail safely within resource limits.
8. Artifact hashes and provenance are persisted and returned with the preview.
9. No automatic publication, merge, deployment, or production mutation is possible.

## Activation gates

This is a design document only. Implementation must be split into reviewable PRs: intent routing and schemas; isolated artifact store; audio MVP; video assembly; independent evaluation; then LINE integration. Each stage requires tests and independent review on the exact commit SHA. Production activation and any external provider use require separate explicit approval.
