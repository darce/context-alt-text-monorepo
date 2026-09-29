---
title: Usage Admission API Contract
boundary_owner: backend
status: draft
since: APP-1
machine_fixture: usage-admission-errors.json
---

# Usage Admission API Contract

This contract covers HTTP errors raised while resolving or reserving usage in
`recognition/interface_adapters/http/deps/usage_admission.py`. FastAPI exposes
the `HTTPException.detail` value under the top-level `detail` key. The normal
typed error body is therefore `{"detail":{"error":"<code>"}}`; the resolver
availability errors retain their string detail as `{"detail":"Usage admission unavailable"}`.

| Status | `detail` error / code | Headers | When raised | Reservation released? | Client retry guidance |
| --- | --- | --- | --- | --- | --- |
| 402 | `allowance_exhausted` | `Retry-After` when the allowance period end is known; otherwise absent | The tenant has no active entitlement with enough remaining allowance. | No ticket is returned and `release()` is not called. | Wait for the indicated period end when supplied. Without the header, check allowance state before retrying. |
| 409 | `usage_fingerprint_conflict` | None | An operation identifier is reused with a different request fingerprint. | No ticket is returned and `release()` is not called. | Retry with the original operation and payload, or use a new operation identifier only for a distinct chargeable request. |
| 503 | `usage_admission_stopped` | None | An operator stop or fence prevents new reservations. | No ticket is returned and `release()` is not called. | Retry with the same operation identifier after the stop is cleared. |
| 503 | `usage_admission_limited` | None | A global daily, in-flight, or queue limit refuses the reservation. | No ticket is returned and `release()` is not called. | Retry with bounded backoff after capacity becomes available, keeping the same operation identifier. |
| 503 | `usage_admission_unavailable` | None | Required global admission state or configuration is missing or invalid during reservation. | No ticket is returned and `release()` is not called. | Retry after the service configuration or state is restored; use bounded backoff and keep the same operation identifier. |
| 503 | `reservation_timeout` | `Retry-After: 5` | The reservation database operation exceeds its deadline. The dependency attempts a transaction rollback before returning the error. | No ticket is returned and `release()` is not called; rollback is attempted. | Retry after the indicated delay with the same operation identifier. |
| 503 | `Usage admission unavailable` (string detail, no error code) | None | The resolver finds a configured service that is invalid, cannot be constructed from the available session, or produces an invalid service. | Admission has not run; no reservation exists to release. | Retry after the service configuration is fixed, with bounded backoff. |

The optional service path is disabled when no service is configured; that case
does not raise an error. Errors raised after a ticket is returned are outside
this table: `admit_usage` releases that ticket if dispatch raises.
