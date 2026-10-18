# E15-3a CORS Origin Decision Record

> Use this record only if Slice 1 requires adding the LocalWP origin to the
> production `RECOGNITION_ALLOWED_ORIGINS` allowlist.

## Decision Summary

| Field | Value |
| --- | --- |
| Decision date | `<YYYY-MM-DD>` |
| Approver | `<name>` |
| Operator | `<name>` |
| Environment | `prod` |
| Added origin | `<scheme://host[:port]>` |
| Lifetime | `<temporary until task close / permanent>` |
| Rollback owner | `<name>` |

## Context

E15-3a requires a LocalWP-resident ACX plugin instance to complete a real
LocalWP -> `api.altcontext.com` -> recognition round trip before any paid
WordPress hosting is provisioned. The production backend gates browser access
through `RECOGNITION_ALLOWED_ORIGINS` in `/opt/acx-backend/prod/.env`.

Record why this origin had to be added instead of reusing an existing
allowlisted origin.

```text
<context>
```

## Decision

The production allowlist was updated to include:

```text
<scheme://host[:port]>
```

Reason for approval:

```text
<reason>
```

## Change Procedure

| Step | Evidence |
| --- | --- |
| `/opt/acx-backend/prod/.env` updated | `<timestamp / operator note>` |
| `RECOGNITION_ALLOWED_ORIGINS` new value recorded securely | `<note>` |
| `sudo systemctl restart acx-prod` executed | `<timestamp>` |
| Post-restart probe succeeded | `<link to run log section>` |

## Risk Review

| Question | Answer |
| --- | --- |
| Is the origin operator-controlled? | `yes / no` |
| Is the origin needed only for E15-3a? | `yes / no` |
| Does the origin expose privileged browser access beyond the task window? | `yes / no` |
| Is a rollback date defined if temporary? | `yes / no` |

## Expiry / Rollback Plan

If the origin is temporary, remove it from `RECOGNITION_ALLOWED_ORIGINS` after
the E15-3a gate closes or fails, then restart `acx-prod`.

```text
<rollback plan and trigger>
```

## Links

- Run log: [E15-3a-localwp-oci-run-log.md](./E15-3a-localwp-oci-run-log.md)
- Task plan: [E15-3a-localwp-oci-roundtrip-task-plan.md](./E15-3a-localwp-oci-roundtrip-task-plan.md)
