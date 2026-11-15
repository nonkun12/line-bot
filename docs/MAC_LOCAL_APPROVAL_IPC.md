# macOS Local Approval IPC — Design Only

## Status and invariant

This is an implementation plan, not an IPC server, approval UI, authentication
mechanism, or desktop adapter. The Computer Use bridge must remain disabled.
Nothing in this document authorizes a Mac permission change or desktop action.

## Preferred trust boundary

Use a native macOS XPC service between the signed local approval UI and a
separate executor/broker process. Do not expose a TCP or localhost HTTP approval
endpoint. Do not let LINE, GitHub Actions, a model process, a shell command, or
a background queue connect to the approval broker.

The broker must validate the connecting process using the XPC connection's
kernel-provided audit token and Security framework code-signing identity. A
claimed PID, bundle identifier, username, environment variable, or request
field is not identity evidence. Validate the expected signing requirement and
the active logged-in user/session independently. If the platform API cannot
establish the required identity, reject the connection.

The UI and broker must be separately identifiable roles. Only the UI role may
request a preview-bound approval; only the executor role may redeem the
resulting one-use capability. Neither role may be impersonated by a client
supplied role string.

## Message protocol

The protocol should be versioned and use typed messages with strict size limits.
It should support only:
- SubmitPreview: send a validated plan to the UI for display; no approval.
- RequestApproval: UI-originated request referencing the exact preview digest
  and explicit selected action IDs.
- RedeemCapability: executor-originated one-use redemption.
- CancelPreview: invalidate a preview and any unredeemed approval.

Every request must carry a protocol version and correlation identifier. The
broker derives caller identity from the authenticated connection, not payload.
Reject unknown fields, oversized messages, stale preview IDs, digest mismatch,
unknown or reordered action IDs, and invalid state transitions.

The preview must be bound to the exact plan digest and canonical ordered action
list. A plan update creates a new preview identity; it never mutates an existing
approved preview.

## State machine

RECEIVED -> DISPLAYED -> USER_SELECTED -> APPROVED -> REDEEMED

Any cancel, UI disconnect, broker restart, session change, timeout, plan
mutation, executor disconnect, or partial execution failure transitions to
INVALIDATED. Invalidated previews cannot be revived. Approval is one-use and
expires within 120 seconds. The broker must maintain replay state in a
crash-safe local store or equivalent broker-owned mechanism; a caller-provided
set or in-memory state in an untrusted process is not sufficient for production.

## Required negative tests before implementation

- Unsigned or wrong-team/wrong-requirement client cannot submit or approve.
- A process with the right UID but wrong signing identity is rejected.
- UI role cannot redeem; executor role cannot display/approve.
- Payload role/PID/UID fields cannot override kernel-derived identity.
- LINE/model/background-worker process cannot reach the broker.
- Disconnect, logout, fast-user-switch, sleep/wake, and broker restart invalidate
  outstanding previews and capabilities.
- Replay after process restart is rejected.
- Duplicate, unknown, reordered, or modified action IDs are rejected.
- Oversized, malformed, unknown-version, and unknown-field messages are rejected.
- Cancellation racing with redemption has one deterministic outcome: either a
  redemption already atomically committed, or cancellation wins; never both.

## Implementation gates

1. Review this design against supported macOS versions and signing/distribution
   model.
2. Build a no-op XPC identity probe with no approval or desktop APIs.
3. Test audit-token and code-signing validation using positive and negative
   signed test clients.
4. Test session lifecycle and invalidation behavior.
5. Implement preview-only UI; verify it cannot issue a capability.
6. Add broker-owned durable one-use redemption and replay tests.
7. Independent security review before connecting any desktop adapter.

Until every gate is reviewed and explicitly approved, XPC is not to be connected
to the existing bridge. Read-only desktop inspection is also disabled.
