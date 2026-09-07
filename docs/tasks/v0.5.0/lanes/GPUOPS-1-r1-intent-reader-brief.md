# GPUOPS-1-R1. Intent reader hardening

Fix wave lane. Base: `feature/gpuops-1`. Owned files only:
`infra/oci/gpu_lifecycle/intent.py`, `infra/oci/gpu_lifecycle/tests/test_intent.py`.

Read `docs/workbay/contracts/gpu-lifecycle.md` for the frozen contract. **Do not edit it**
or anything else under `docs/workbay/` — the sandbox cannot round-trip those paths.

## Defects to close

**M-04 — reader accepts malformed payloads.** `read_intent` currently accepts an intent
file that omits `ttl_seconds`, carries a non-UUID `nonce`, or is missing other
contract-required fields, and still yields an effective START or STOP. The contract says a
malformed intent is logged at WARNING and treated as `auto`.
Require and strictly validate every contract field: `schema_version`, `action` in
{start,stop,auto}, `requested_at`, `expires_at`, `ttl_seconds` (positive int),
`requested_by` (non-empty str), `nonce` (UUID4). Anything else → treat the file as `auto`
and log once at WARNING with the failing field name.

**M-05 — future-dated `requested_at` dominates.** A file dated well in the future is never
"expired", so it wins the newest-unexpired-wins precedence indefinitely, and expiry is
anchored to that future timestamp. Reject `requested_at` more than a small clock-skew
tolerance (make it a module constant, default 120s) ahead of reader-now, and clamp the
effective expiry against reader-now rather than trusting the file's own anchor. The
existing 7200s `expires_at` clamp stays.

**CANON-04 — wall-clock-only authority token.** The whole grant rests on two wall-clock
ISO strings; a backwards NTP correction on the backend silently re-arms an already-expired
`start`, which is exactly the arm that suppresses idle reap and disables the cost governor.
This repo already rejected that pattern once: `RunningSinceLeaseStore.age_seconds` in
`reaper.py` refuses non-monotonic origins with "Persisted lease metadata is unsafe to use
as a duration origin". Apply the same discipline here at the reader boundary: a grant whose
effective age cannot be established within the skew tolerance is not honoured. You own only
`intent.py` — implement the fence in the reader (skew tolerance + clamped expiry + a
recorded reason on the parsed result), do not reach into `reaper.py`.

## Definition of done

- Every new behaviour is TDD'd in `tests/test_intent.py`: one test per malformed shape
  (missing ttl, bad nonce, missing requested_by, bad action, wrong schema_version),
  one for future-dated `requested_at`, one for skew-tolerance boundary, one asserting the
  existing 7200s clamp still holds.
- Existing automatic behaviour stays pinned — do not weaken any existing assertion.
- `python3 -m pytest infra/oci/gpu_lifecycle/tests/test_intent.py infra/oci/gpu_lifecycle/tests/test_intent_controller.py -q -p no:cacheprovider` green.
- Commit on `feature/gpuops-1-r1-intent-reader` with subject
  `gpu lifecycle: strict intent schema validation and clock-skew fencing`.
- **Commit early and often.** Make your first commit within the first quarter of the turn,
  even if incomplete. A turn that hits the wall clock with uncommitted work loses all of it.
  Never end on `needs_guidance` with uncommitted changes.
- No AI attribution trailers in commit messages.
