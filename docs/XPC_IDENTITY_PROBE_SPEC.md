# No-op macOS XPC Identity Probe — Specification

## Status

Specification only. No Swift target, XPC listener, entitlement, signing change,
host permission change, or desktop API is added by this document. The existing
Python bridge remains unconditionally disabled. This probe must never approve,
redeem, inspect, or execute a desktop plan.

## Objective

Prove only that a broker can distinguish an expected signed test client from
untrusted clients using OS-provided connection identity. The probe must not
treat a successful connection as user approval or execution authority.

## Minimal architecture

- A short-lived, separately signed test broker exposes one fixed XPC interface.
- A separately signed positive test client sends a constant probe message.
- Negative test clients vary one trust property at a time.
- The broker obtains the connection audit token from the XPC connection and
  derives code-signing identity with Security.framework APIs.
- The broker compares the result against a pinned designated requirement and
  expected role configuration shipped with the test build.
- Claimed PID, UID, username, bundle ID, team ID, role, environment variables,
  and message fields are diagnostic input only; none can satisfy identity checks.
- The only response is a bounded verdict and reason code. No plan, file path,
  screenshot, capability, approval token, or arbitrary payload is accepted.

## Probe message contract

Protocol version: integer constant selected at build time.

Request fields:
- protocol_version
- request_id: bounded opaque correlation value
- probe_nonce: bounded random value

Reject unknown fields, duplicate fields, oversized messages, malformed values,
unsupported versions, and replayed probe nonces. The broker obtains caller
identity independently of all request fields.

Response fields:
- protocol_version
- request_id
- verdict: ACCEPTED_TEST_IDENTITY or REJECTED
- reason_code: stable non-sensitive enum

The response must not expose raw audit tokens, signing material, filesystem
paths, or personal account identifiers. Logs record only test case ID, verdict,
reason code, and timestamp.

## Required positive case

1. Build and sign broker and positive client with the test-only signing setup.
2. Pin the exact expected designated requirement in broker test configuration.
3. Launch the client in the intended logged-in user session.
4. Confirm the broker derives the expected identity from the XPC connection.
5. Confirm a constant probe receives ACCEPTED_TEST_IDENTITY.
6. Confirm the response conveys no approval or execution authority.

A positive result proves only test-client identity recognition. It does not
prove that the user approved an action or that a desktop operation is safe.

## Required negative cases

| Case | Manipulation | Required result |
|---|---|---|
| Unsigned client | Remove signature | REJECTED |
| Wrong signer | Sign with another test identity | REJECTED |
| Wrong requirement | Same team, non-matching designated requirement | REJECTED |
| Claimed identity spoof | Send expected PID/UID/team/bundle/role in payload | REJECTED |
| Role confusion | Positive client claims broker or executor role | REJECTED |
| Wrong user session | Connect from a different user/session context | REJECTED |
| Protocol downgrade | Send unsupported older version | REJECTED |
| Oversized message | Exceed strict request bound | REJECTED |
| Replay | Reuse probe nonce | REJECTED |
| Unknown field | Add unrecognized request field | REJECTED |
| Broker restart | Reuse pre-restart nonce where replay persistence is required | REJECTED |

Tests must demonstrate that spoofed payload claims never change the identity
verdict. Test fixtures must not be described as evidence of real macOS identity.

## Security and lifecycle constraints

- Use a private XPC service name; do not create a TCP or localhost listener.
- No launch-at-login or background persistence for the probe.
- No broad entitlements, accessibility permissions, screen-recording
  permissions, automation permissions, or Full Disk Access.
- No connection from LINE, GitHub Actions, model processes, shell wrappers, or
  background workers.
- Bound request size, response size, connection count, and request duration.
- Fail closed on missing audit token, Security.framework errors, ambiguous
  identity, session lookup failure, or broker restart.
- The broker must not load plugins, run shell commands, open documents, or call
  any CAD/Excel/Calc API.
- Remove test signing identities and temporary artifacts after test completion
  using a reviewed cleanup procedure; never delete user data.

## Acceptance gates

The probe is not implementation-ready until the supported macOS versions,
Xcode/Swift toolchain, signing model, and test distribution method are reviewed.
After implementation, require:
- positive signed-client test;
- all negative cases above;
- independent verification of audit-token-to-code-signing validation;
- lifecycle/restart/replay tests;
- static inspection confirming no desktop API or approval path exists;
- independent security review.

Even if every probe test passes, the production approval UI, broker-owned
durable one-use capability redemption, and desktop adapters remain separate
projects requiring separate review and explicit authorization.

## Current invariant

The probe is not connected to `core/computer_use_bridge.py`. The bridge's
`snapshot` and `execute` methods must continue to raise
`DesktopExecutionDisabled` under all inputs. No Mac-side operation is
authorized by this specification.
