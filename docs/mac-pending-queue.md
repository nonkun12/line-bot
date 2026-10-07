# Mac Pending Queue

The pending queue is the durable boundary between cloud-facing requests and the Mac-local execution layer.

## Intended flow

LINE / cloud request → queue record → Mac becomes available → approve/claim → Hermes Kanban adapter → verification / Safety Gate → terminal queue state → Obsidian record

Mac OFF does not delete or complete work. A request remains PENDING.

## State contract

- PENDING: durable and not currently executing.
- RUNNING: atomically claimed by one worker.
- PASS: terminal success recorded only after verification.
- FAILED: terminal failure recorded.
- BLOCKED: safety or approval boundary prevented execution.

An interrupted RUNNING task is explicitly recovered to PENDING; it is never implicitly converted to PASS.

## Approval boundary

By default, queue entries require approval. claim_next() cannot claim an unapproved task. Approval is a separate operation so later integrations cannot silently turn queue ingestion into execution authority.

## Hermes boundary

This PR does not call Hermes or modify the Hermes Kanban database. A future Mac-local adapter should translate one claimed queue task into one Hermes task and reconcile completion from verifiable evidence. A text response from an AI must not by itself mark a queue item PASS.

## Obsidian boundary

Obsidian remains downstream of verification. Queue completion does not grant filesystem mutation authority. A future integration should write an audit record only after the configured Safety Gate permits the operation.

## Recovery

On Mac startup, the local worker can inspect RUNNING records left by an interrupted process and recover them to PENDING. Retry limits and stale-run policy should be added at the worker layer after real Mac/Hermes testing.