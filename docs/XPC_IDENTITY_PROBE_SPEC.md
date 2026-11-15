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
- The broker configures the XPC connection's documented peer code-signing
  requirement before accepting or processing requests. The operating system
  enforces that requirement; the probe does not need to extract an audit token
  merely to establish the peer's signing requirement.
- The broker uses only documented peer/session attributes for additional
  session checks. Claimed PID, UID, username, bundle ID, team ID, role, and
  environment variables remain untrusted diagnostic input.
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


## API selection note — peer signing enforcement

Do not make audit-token extraction a prerequisite for this no-op probe. The
primary identity gate should be the operating system's documented XPC
peer-code-signing requirement API:

- High-level Foundation path: configure
  `NSXPCConnection.setCodeSigningRequirement(_:)` on the peer connection
  before `resume()`, or configure
  `NSXPCListener.setConnectionCodeSigningRequirement(_:)` for incoming
  connections. A malformed requirement is a programming error; a peer that
  does not match causes the connection to be invalidated.
- Lower-level libXPC path: configure
  `xpc_connection_set_peer_code_signing_requirement` on the connection before
  processing messages. Apple documents that the system checks the peer's
  code-signing requirement as it sends messages.

The probe must pin a narrowly scoped designated requirement for the expected
test client. A team identifier alone may be too broad if multiple executables
from that team are trusted. The exact requirement must be reviewed against the
actual signing identity and distribution method.

Use peer PID/UID/GID/audit-session attributes only for supplementary session
policy and diagnostics, never as a replacement for code-signature enforcement.
Do not use a caller-supplied PID or a PID-only lookup as identity proof.

The public references consulted:
- [NSXPCConnection.setCodeSigningRequirement(_:)](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement(_:))
- [NSXPCListener.setConnectionCodeSigningRequirement(_:)](https://developer.apple.com/documentation/foundation/nsxpclistener/setconnectioncodesigningrequirement(_:))
- [xpc_connection_set_peer_code_signing_requirement](https://developer.apple.com/documentation/xpc/xpc_connection_set_peer_code_signing_requirement(_:_:))
- [TN3127: Inside Code Signing: Requirements](https://developer.apple.com/documentation/technotes/tn3127-inside-code-signing-requirements/)
- [Apple Developer Technical Support: Validating Signature Of XPC Process](https://developer.apple.com/forums/thread/681053)

Do not add a separate Security.framework audit-token validation step unless
the selected public API family and target SDK provide a documented, supported
way to obtain the token and an independent review establishes that it adds a
necessary security property. Do not use undocumented/private APIs. Compilation
and positive/negative runtime verification on the actual Mac remain mandatory.

## Deployment-target decision gate

Apple Developer Technical Support has documented these availability boundaries:
- `NSXPCConnection.setCodeSigningRequirement(_:)`: macOS 13 and later.
- `xpc_connection_set_peer_code_signing_requirement`: macOS 12 and later.
- `xpc_connection_set_peer_lightweight_code_requirement`: macOS 14.4 and later.

References:
- [Apple Developer: NSXPCConnection.setCodeSigningRequirement(_:)](https://developer.apple.com/documentation/foundation/nsxpcconnection/setcodesigningrequirement(_:))
- [Apple Developer: xpc_connection_set_peer_code_signing_requirement](https://developer.apple.com/documentation/xpc/xpc_connection_set_peer_code_signing_requirement(_:_:))
- [Apple Developer: XPC lightweight code requirement](https://developer.apple.com/documentation/xpc/xpc_connection_set_peer_lightweight_code_requirement(_:_:))
- [Apple Developer Forums: Validating Signature Of XPC Process](https://developer.apple.com/forums/thread/681053) (Apple Developer Technical Support guidance; verify against the selected SDK headers and deployment target).

Do not pick an API until the minimum supported macOS version is explicitly
selected. For a target below the API's availability, do not silently fall back
to PID/UID checks, payload identity, undocumented APIs, or a weaker scheme.
Stop and revise the supported-version policy instead. These version boundaries
are planning inputs; the selected SDK's availability annotations and actual
Mac compilation remain authoritative.
