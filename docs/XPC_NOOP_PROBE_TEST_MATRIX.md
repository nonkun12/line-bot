# XPC No-Op Probe: Mac-Side Test Matrix

Status: test specification only. No Swift target, XPC service, signing
configuration, entitlement, LaunchAgent, or desktop operation is implemented.

## Purpose and strict boundary

Prove only that the intended signed probe client can establish an XPC
connection to the intended signed probe broker under an OS-enforced
code-signing requirement, and that deliberately invalid peers are rejected.
After OS-authenticated XPC connection establishment, the client sends BeginProbe
(version and request ID); the broker returns a cryptographically random
connection-bound challenge. The client includes that challenge, the version,
request ID, and a random nonce in Probe. The broker returns a verdict and fixed
reason code.

This probe does not authenticate a human, approve a plan, issue a capability,
read or write files, capture screenshots, inspect CAD/spreadsheets, or invoke
Accessibility, Apple Events, Automation, or shell commands.

## Preconditions — stop if any item is unknown

- Minimum supported macOS version and actual test OS build are recorded.
- Xcode version, SDK version, deployment target, and architecture are recorded.
- Broker and client bundle identifiers, designated requirements, signing
  identity, and distribution model are reviewed and pinned.
- The selected public XPC API is available in the selected SDK and deployment
  target. No runtime fallback to PID/UID checks or private APIs is permitted.
- Broker and client are separate signed executables with distinct roles.
- Probe runs only on a disposable test account or test machine.
- No launch-at-login registration or persistent background service is added.

## API directionality

For a client-initiated connection, the client must enforce the expected broker
signature on its outgoing connection. The broker must enforce the expected
client signature on the accepted incoming connection, before resuming or
processing it. A check in only one direction is insufficient.

Prefer a listener-wide requirement only when one fixed client identity is
appropriate for every accepted connection. Otherwise apply the requirement to
the individual accepted connection in the listener delegate before it resumes.
The exact API spelling and availability must be confirmed against the chosen
SDK headers. Do not configure multiple peer code-signing requirement APIs on
the same connection.

## Test matrix

| ID | Test | Expected result | Evidence |
|---|---|---|---|
| P01 | Correctly signed probe client to correctly signed broker | Accepted | Broker and client fixed verdict logs |
| N01 | Unsigned client | Rejected by OS signing requirement | Client connection error and broker no-request evidence |
| N02 | Client signed by a different team | Rejected | Same |
| N03 | Same team, wrong designated requirement / wrong executable identity | Rejected | Same |
| N04 | Correct client, broker signed with wrong identity | Client rejects broker | Client connection error |
| N05 | Correctly signed client supplies false PID, UID, bundle ID, or role claims | Claims ignored; authenticated signing verdict is unchanged | Compare equivalent requests with and without spoofed claims; no identity field is trusted |
| N06 | Wrong protocol version | Rejected after authenticated connection | Fixed protocol error |
| N07 | Unknown fields or oversized message | Rejected; process remains healthy | Fixed malformed-message error |
| N08 | Reused nonce/request ID within one broker instance | Rejected by in-memory probe replay guard | Fixed replay error |
| N09 | Broker restart followed by replay of a captured old Probe and old connection challenge | Rejected because restart destroys the old connection; a new connection has a different challenge | Restart/replay test log; verify no persistent replay/approval store |
| N10 | Client disconnect during request | No partial approval or side effect; request discarded | Broker state trace |
| N11 | Wrong user or audit session | Rejected by independent session policy | OS-derived session evidence |
| N12 | Broker or client crashes during test | No persistent approval state; next run starts fail-closed | Restart test log |

## Required assertions

- The OS enforces peer code-signing requirements before application messages
  are handled.
- The broker derives peer identity from the authenticated XPC connection;
  payload identity fields are never trusted. A correctly signed client that
  sends false identity claims must not be rejected solely because those
  untrusted claims differ; the claims are ignored and the signing verdict stays
  unchanged.
- The probe emits no raw signing material, process arguments, audit token,
  workbook contents, CAD data, screenshot, or capability.
- No listener is exposed over TCP/HTTP/localhost networking.
- No XPC endpoint or message handler is reachable from LINE, GitHub Actions,
  model providers, shell commands, or background workers.
- No file, application, or desktop APIs are linked or invoked.
- Rejection paths are observable through fixed reason codes without exposing
  sensitive identity material.
- Each authenticated connection receives its own unpredictable challenge, held
  only in broker memory and bound to that connection. Disconnect or restart
  destroys it; a captured old Probe cannot be replayed on a new connection.
  The nonce replay set is also memory-only. No durable approval state or replay
  database is created.

## Evidence package

For every run, retain only:
- OS version/build, Xcode version, SDK and deployment target;
- test binary hashes and signing identity summaries;
- exact pinned code-signing requirement strings (reviewed, non-secret);
- test ID, pass/fail, fixed reason code, and timestamp;
- source revision and reviewer sign-off.

Do not retain screenshots, user documents, raw audit tokens, or unrelated
system logs. No durable replay database or approval state is written.

## Exit criteria

All P01 and N01–N12 tests pass on the selected real Mac/OS build; static review
confirms there are no desktop APIs or network listeners; signing requirements
are independently reviewed; and an independent security reviewer signs off.
Any missing evidence, API availability ambiguity, or unexpected acceptance is
a failure. The Python bridge remains disabled until a separate approval
authorizes a later milestone.
