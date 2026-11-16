# Durable Job Idempotency

## Contract

Job registration may supply an optional `idempotency_key`. The key is persisted
in SQLite and protected by a unique partial index scoped to `user_id`.
Repeating the same key for the same user and request payload returns the
original job ID. Reusing that user's key for a different payload raises
`ValueError` and does not create another job. Different users may use the same
key independently.

The request fingerprint covers user ID, message, job type, source, parent job
ID, and retry limit. The key lookup and insert run inside `BEGIN IMMEDIATE`,
so concurrent retries serialize at the database boundary.

## Compatibility

Callers that omit `idempotency_key` retain the existing create-new-job behavior.
Existing databases are migrated additively by `init_db`; existing rows keep a
NULL key and are unaffected.

## Safety boundary

This prevents duplicate job records for callers that provide a stable key. It
does not by itself guarantee exactly-once external side effects, fence stale
workers, or make arbitrary distributed dispatch idempotent. Those require
executor-side idempotency and a lease/fencing protocol and remain unimplemented.
