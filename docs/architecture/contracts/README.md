# Architecture Contracts Documentation

Contracts describe the live integration between the prototype WordPress plugin
(`apps/prototype-wp-alt-context`) and the prototype description service
(`apps/prototype-description-service`). These documents focus on the APIs that
are implemented today, not legacy plans.

## Contents

### WordPress Workbench (WP REST)

- `clustering-api.md` - Workbench recognition endpoints under
  `/wp-json/acx/v1/workbench/recognition/*`.
- `workbench/media.json` - Sample response for
  `/wp-json/acx/v1/workbench/media`.

### Recognition Service (FastAPI)

- `recognition-clustering.md` - Recognition service HTTP API under
  `/recognition/*` (analyze jobs, clustering, suggestions, media identities,
  events, health).

## Notes

- Workbench endpoints proxy to the recognition service and inject `tenant_id`
  derived from the WordPress site URL (md5 hash).
- Recognition service auth uses `Authorization: Bearer <api-key>` by default;
  the header name can be configured via `RECOGNITION_API_KEY_HEADER`.
- Legacy v2 identify and sanitization/validation contracts were removed from
  this directory because they do not reflect the current prototype.
