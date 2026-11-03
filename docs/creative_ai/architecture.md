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

## First end-to-end performance milestone: handbell

The first concrete creative deliverable is a handbell arrangement that is genuinely ready for performers, not merely a musical idea or a rendered demo.

The Goal should produce and validate:

1. A complete score with key/time signature, tempo, measure numbers, dynamics, articulation, rests, accidentals, and clear entrances/cutoffs.
2. A playable bell assignment: each pitch mapped to an available bell, with octave/range and accidental coverage checked. If the requested bell inventory is unknown, ask for it or produce a clearly labelled provisional arrangement rather than claiming playability.
3. Performer parts: one readable part per player or station, including bell handoffs, simultaneous-note constraints, ringing/damping instructions, and page turns where relevant.
4. A machine-readable event/MIDI representation with exact onset, duration, pitch, velocity/dynamics, and performer/bell assignment.
5. A rehearsal audio render and, where practical, separated performer/station guide tracks. The render is a rehearsal aid and must not substitute for the score.
6. Independent music review: check range, collisions, impossible hand assignments, missing notes, rhythm alignment, score-to-MIDI consistency, and whether every part can be performed with the declared inventory.
7. A delivery package containing score PDF or MusicXML, MIDI, audio preview, performer parts, inventory assumptions, and provenance/license metadata.

Handbell job chain (illustrative, each step persisted and evidence-gated):

`music.brief` -> `music.inventory_check` -> `music.compose` -> `music.arrange_for_bells` -> `music.generate_score` -> `music.generate_parts` -> `music.export_midi` -> `audio.render_rehearsal` -> `music.critic_review` -> `music.repair` (only if needed) -> `creative.package`.

The chain may continue through multiple repair/review cycles within the Goal grant and job budget. If the bell inventory, performer count, or required musical standard is unknown, the Goal records the assumption and requests only the missing essential information. No PASS is allowed merely because a file exists or a renderer exits successfully.

## Video production follows the same Goal discipline

Video is a full specialist workflow, not just a renderer. Its dependent jobs cover brief, script, storyboard, asset rights/ingestion, shot/timeline plan, edit decision list, audio synchronization, render, technical QC, editorial critic, repair, and package delivery. Existing image-understanding results may inform shot selection and continuity, while the image-reading capability itself remains a reusable upstream specialist. Video and music exchange artifact IDs and timing metadata through the Goal contract.

## Orchestration invariants

- All specialist work is scheduled through the durable Goal chain; no specialist bypasses dependency, grant, budget, or evidence checks.
- Empty queues trigger bounded planning/generation for unmet criteria; repeated empty generation, duplicate keys, cycles, or budget exhaustion become explicit HOLD reasons rather than silent success.
- Safe, pre-registered in-scope child jobs may continue under one goal-scoped grant. New privileges, protected paths, external publishing, paid providers, production mutations, merge, and deploy remain outside that grant.
- Retries are idempotent and bounded. A repair job must reference the failed evidence and remain within the original Goal scope.
- The critic is independent of the producing specialist and checks the actual output artifacts, not only the specialist's completion message.
- Goal completion requires all acceptance criteria to pass with persisted evidence and artifact hashes.
