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


## Orchestral specialist architecture

Goal AI is the conductor and the durable Goal/child-JOB chain is the score and timing system. Specialists are peers with explicit contracts; none is treated as an optional side feature. A specialist may propose work, but only the Goal orchestrator schedules it, checks dependencies and budgets, and accepts independently verified evidence.

Initial specialist roles:

- Image understanding: reuse the repository's existing image-reading capability after its exact entry point, input contract, and tests are confirmed. Do not create a duplicate image reader. It supplies structured visual observations and source-artifact references to downstream specialists.
- Music: composition, arrangement, notation, part allocation, MIDI/event generation, audio rendering, and listening/score validation.
- Video: concept, script, storyboard, shot list, timeline, editing, rendering, captions, and audio synchronization.
- Creative critic: independent checks for musical correctness, visual continuity, technical format validity, rights/provenance, and user acceptance criteria.
- Goal conductor: maintains the overall objective, creates typed dependent jobs, allocates bounded resources, handles retries/repairs, and decides achieved/HOLD from evidence.

Specialists communicate through versioned artifact manifests and typed JOB results, not hidden shared state or free-form agent-to-agent commands. Each child JOB records its parent/dependencies, inputs, outputs, tool identity, limits, evidence, and idempotency key. A specialist cannot grant itself permissions or mark the overall Goal achieved.

## General-purpose music production milestone

Music production is a general-purpose specialist capability. Handbell is only one possible example of an arrangement request; it is not a dedicated implementation target or a hard-coded first product.

The music specialist should support a range of user-defined formats and ensembles through typed, reusable jobs:

1. Interpret the brief and record genre, mood, duration, instrumentation, audience, and delivery format.
2. Compose and arrange using a structured, editable representation rather than a prompt-only description.
3. Validate musical structure, timing, pitch/range, instrument constraints, and consistency between source notation and exported artifacts.
4. Export appropriate deliverables such as MusicXML, MIDI, notation/PDF, stems, or other formats supported by available local tools.
5. Render audio previews locally when an eligible synthesizer, sound library, and sufficient resources are available.
6. Run an independent critic against the user's acceptance criteria and the actual generated artifacts; create bounded repair jobs for concrete defects.
7. Package outputs with provenance, licenses, assumptions, and clear disclosure of any unavailable deliverables.

Instrument-specific constraints (including handbell inventory, performer assignments, and ringing/damping techniques) belong in optional specialist validators selected only when the user's brief calls for them. They must not constrain the general music pipeline.

## Video production follows the same Goal discipline

Video is a full specialist workflow, not just a renderer. Its dependent jobs cover brief, script, storyboard, asset rights/ingestion, shot/timeline plan, edit decision list, audio synchronization, render, technical QC, editorial critic, repair, and package delivery. Existing image-understanding results may inform shot selection and continuity, while the image-reading capability itself remains a reusable upstream specialist. Video and music exchange artifact IDs and timing metadata through the Goal contract.

## Orchestration invariants

- All specialist work is scheduled through the durable Goal chain; no specialist bypasses dependency, grant, budget, or evidence checks.
- Empty queues trigger bounded planning/generation for unmet criteria; repeated empty generation, duplicate keys, cycles, or budget exhaustion become explicit HOLD reasons rather than silent success.
- Safe, pre-registered in-scope child jobs may continue under one goal-scoped grant. New privileges, protected paths, external publishing, paid providers, production mutations, merge, and deploy remain outside that grant.
- Retries are idempotent and bounded. A repair job must reference the failed evidence and remain within the original Goal scope.
- The critic is independent of the producing specialist and checks the actual output artifacts, not only the specialist's completion message.
- Goal completion requires all acceptance criteria to pass with persisted evidence and artifact hashes.


## Free-only operating policy (mandatory)

The project must remain usable without paid subscriptions, paid APIs, usage-based model endpoints, or newly purchased storage/compute. This is a hard constraint, not a default that can be silently relaxed.

- Default to local, open-source tools already available on the user's own machines or existing free infrastructure. Check actual hardware, disk, memory, and runtime availability before proposing a model download or workload.
- Do not call paid hosted music/video/image generation APIs. Do not add billing credentials, payment methods, or paid-provider SDKs. Remote inference is disabled by default; any future exception would require a separate explicit user decision and is outside this free-only plan.
- Prefer deterministic open formats and local tools: MusicXML/MIDI for scores and performance events; a locally installed synthesizer and legally usable soundfont for rehearsal audio; FFmpeg for video assembly; and locally available image/audio analysis where practical.
- A tool or model is eligible only after its license, redistribution/use restrictions, model size, hardware requirements, and ongoing resource cost are checked. "Open source" does not automatically mean unrestricted commercial or public use.
- Never assume that a free tier is permanent, sufficient, or suitable for autonomous production. Do not build core Goal completion on a vendor free tier, trial, or quota.
- If local hardware cannot complete a task within the configured limits, preserve the Goal and artifacts, report a truthful HOLD with the resource reason, and offer a smaller local workflow. Never fall back to a paid endpoint.
- Use existing free storage and retention only within known limits; enforce quotas, cleanup previews and intermediates safely, and do not create paid storage resources.
- Keep the same restrictions in tests: assert that provider selection cannot silently choose a paid/remote adapter and that missing local tools cause HOLD rather than paid fallback.

For the handbell milestone, the first deliverables should be generated from structured note/event data into MusicXML/MIDI and rendered locally only when an eligible local synthesizer and soundfont are available. The score and parts remain the authoritative performance materials; a missing audio renderer must not prevent score validation or be disguised as a completed audio deliverable.
