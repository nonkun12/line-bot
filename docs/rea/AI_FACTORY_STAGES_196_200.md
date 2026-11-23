# AI Factory Stages 196-200 — Execution Provenance

## Purpose

Stages 196-200 strengthen the trust boundary of the Stage 191-195 capability benchmark pipeline. They bind a supplied Stage 192 run record to model/runtime identity, dataset provenance, a privacy-minimized environment fingerprint, and signed attestations.

These stages validate evidence supplied by external systems. They do not execute a model, independently inspect a runner, prove sandbox isolation, or establish that a claimed hardware identity is true.

## Stage contracts

- **196 — Model/runtime manifest:** binds candidate ID and exact model artifact SHA-256 to runtime name/version, inference engine/version, and runtime image digest.
- **197 — Dataset provenance:** binds a frozen dataset digest to source-manifest and preprocessing digests, usage-policy label, and provenance-record ID.
- **198 — Environment attestation:** records OS, architecture, hardware class, runtime-configuration digest, dependency-lock digest, attestor identity, and explicit assurance level. Hostnames, serial numbers, IP addresses, and other direct host identifiers are intentionally excluded.
- **199 — Execution binding:** validates Stage 191 suite and Stage 192 run signatures and digests, requires exact candidate/artifact agreement with Stage 196, verifies Stage 197 and 198 evidence, then signs a single binding over all identities and a unique caller-supplied nonce.
- **200 — Provenance certificate:** revalidates the binding digest/signature and emits a proposal-only certificate. A hardware-signed level can be required by policy; the verifier does not itself provide a hardware trust root.

## Assurance semantics

self_reported means the named attestor signed the environment claims. hardware_signed is only a claim label that must be backed by an independently configured hardware-attestation verifier and trust root outside this module. Setting that label or passing a signature callback does not establish hardware truth.

Signatures prove that a configured signer attested to a digest. They do not prove that a process actually executed, that the runtime was isolated, that the dataset was ethically or scientifically appropriate, or that telemetry is accurate. Nonces are included to support replay tracking; deployments must persist and reject previously accepted nonces in a trusted registry. This module does not claim global replay prevention without that registry.

## Safety and limitations

All five stages fail closed on HOLD, invalid digests/signatures, mismatched artifacts, incomplete identity binding, or tampering. Outputs remain proposal-only. Model activation, weight mutation, merge, and deployment authorization are always false. No model inference, local Mac operation, paid API, cloud fallback, workflow dispatch, or production mutation is performed.

A valid certificate means the supplied claims are internally consistent and signed under the configured verification callbacks. It is not proof of model capability, general intelligence, or ASI. Actual execution attestation requires an independently operated runner, key custody, dataset governance, hardware trust roots, and persistent nonce/revocation controls.
