# UHIP Application Adapter Contract

## Purpose

UHIP is a generic human-input foundation. It MUST NOT depend on AI Secretary semantics.

The UHIP core produces authenticated, validated **Universal Events**. Application-specific meaning is introduced only at an Application Adapter boundary.

```
Human input
  -> local recognition
  -> Recognition Gate
  -> Universal Event
  -> UHIP Core
  -> Application Policy Gate
  -> Application Adapter
  -> application-specific actuator
```

AI Secretary is one adapter among many.

## Adapter responsibilities

An Application Adapter:

1. declares the applications, event types, and risk levels it accepts;
2. validates the Universal Event schema and freshness;
3. maps generic events to application-specific intents;
4. applies its own policy and approval rules;
5. revalidates the target immediately before actuation;
6. uses idempotency based on `event_id`;
7. honors the global Kill Switch and UHIP safety state;
8. records minimal audit information without retaining raw sensor data by default.

An adapter MUST NOT:

- change recognition semantics to suit one application;
- bypass the UHIP Recognition Gate;
- bypass the applicable Policy Gate;
- expand its own permissions;
- execute arbitrary commands from event text;
- treat voice, transcript, or AI-generated text as authorization by itself;
- continue actuation after Kill Switch, heartbeat loss, expiry, or safety-state failure.

## Capability declaration

Adapters should declare capabilities explicitly. A capability should identify at least:

- adapter id and version;
- supported event modalities/types;
- permitted target applications or bundle identifiers;
- maximum risk level;
- whether explicit confirmation is required;
- actuator type;
- policy/rule version.

Example:

```json
{
  "adapter_id": "browser",
  "version": "0.1",
  "modalities": ["hand"],
  "events": ["thumb_up", "swipe_left", "swipe_right"],
  "targets": ["com.apple.Safari"],
  "max_risk": "low",
  "confirmation": "policy",
  "actuator": "separate_process"
}
```

This is a declaration, not an authorization grant. The runtime remains responsible for enforcing the effective capability set.

## Generic event boundary

Recognition MUST remain application-agnostic.

For example, recognition may emit:

```json
{
  "modality": "hand",
  "payload": {
    "gesture": "thumb_up",
    "phase": "end"
  }
}
```

It must NOT emit application commands such as:

- `send_line_message`
- `open_terminal`
- `play_music`
- `merge_pull_request`

The adapter decides whether and how a generic event maps to an application action.

## Policy and risk

Risk classification belongs to the application/action layer, not to the recognition model alone.

A low-confidence recognition event should be rejected before it reaches an adapter. A high-risk application action should still be rejected or require stronger approval even when recognition confidence is high.

Approval bindings must be created by the application Policy Gate from the concrete action, target, parameters, expiry, and applicable policy version. Recognition events do not carry approval identifiers.

## Target revalidation

Immediately before actuation, the adapter MUST verify that the actual target still matches policy.

For desktop automation this includes, where applicable:

- focused application Bundle ID;
- secure-input state;
- accessibility permission state;
- target/window context;
- current safety state.

Window titles alone are not a sufficient identity check.

## Safety state

Adapters MUST honor these global states:

- `RUNNING`
- `PAUSED`
- `DEGRADED`
- `LOCKED`

Any timeout, heartbeat failure, kill-switch activation, or failed revalidation must fail closed.

The Kill Switch MUST remain outside the recognition process so recognition failure cannot prevent intervention.

## Example adapters

The same UHIP event stream can serve independent adapters such as:

- AI Secretary
- Web Browser
- Media Player
- Presentation Controller
- Development Environment
- Accessibility Controls
- Generic Desktop Automation
- future Smart Home integrations

Each adapter is independently policy-controlled.

## Phase 0 boundary

Phase 0 remains camera-only, local, and observation/replay focused.

No adapter may perform OS actions in Phase 0. The adapter contract is being defined now so that later phases do not accidentally couple UHIP to AI Secretary.

Phase 0 therefore validates the generic event boundary and deterministic replay without granting actuation capability.

## Security invariant

**No application adapter may turn an untrusted human-input event into an irreversible action without passing the applicable policy, freshness, target, approval, and global safety checks.**
