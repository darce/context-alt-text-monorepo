# Roster Pending References

This note preserves a deferred roster UX and model-quality idea that was previously stored as a rule file. It describes proposed future behavior, not the current runtime contract.

## Current State

- Auto-matched observations can be attached directly to a roster entry.
- Reference attachment currently appends the embedding immediately.
- There is no operator confirmation queue before the embedding becomes durable model input.

## Deferred Proposal

Add a `pendingReferences` holding area for auto-matched references so operators can confirm or reject them before the embedding is appended to the roster model.

Target flow:

1. Auto-match assigns the observation to a roster entry.
2. The reference is stored as pending instead of being appended immediately.
3. The UI surfaces pending-reference counts and review actions.
4. Confirm generates the embedding and moves the reference into the confirmed set.
5. Reject removes the pending item and unlinks the mistaken auto-match.

Potential follow-on scope:

- confirm/reject endpoints
- pending-reference list/read models
- bulk confirm/reject actions
- migration for existing roster entry schema
- tests covering rejection recovery and repeated-confirm stability

## Placement Rule

This belongs in deferred planning until a task plan or epic explicitly activates it. It should not be loaded as a standing repo rule for routine implementation work.
