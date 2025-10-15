# Recognition Service Authentication Expectations

This note documents the near-term contract between the WordPress plugin and the recognition-service API. It clarifies how requests are authenticated today, how credentials are distributed, and what safeguards are in place (or still pending) so that cross-repo work stays aligned.

## Transport

- All requests to the recognition-service MUST be made over HTTPS when deployed. Local development can use HTTP on `localhost` but staging/prod MUST terminate TLS.
- The plugin sends an `Authorization: Bearer <token>` header on every roster and recognition call. That header is optional in local smoke tests but is required in deployed environments.

## Credential Source of Truth

- The service reads the expected token from the `RECOG_API_KEY` environment variable at startup.
- The WordPress plugin stores the same value in its settings table (`context_alt_text_recognition_api_key`) and exposes it in the admin settings screen.
- A shared `.env.example` entry documents the variable name so both apps stay in sync.

## Request Expectations

- Clients include the bearer token for `POST /api/v0/analyze-scene`, `POST /api/v0/embeddings`, and all `/api/v0/roster` routes.
- Missing or incorrect tokens should return `401 Unauthorized` once enforcement lands. For now the dependency is optional to keep integration tests lightweight.
- Idempotency keys and pagination parameters are orthogonal to auth and continue to work the same way when auth is enabled.

## Operational Guidance

- Rotate keys by updating `RECOG_API_KEY` on the service and the WordPress setting, then triggering a cache flush on the plugin so subsequent requests pick up the new value.
- The long-term plan is to issue per-site keys and check them against an account service (see `roadmap-v3`). Until then, a single shared key per deployment is sufficient.
- If we move the service behind Hugging Face Spaces or another managed host, provision secrets through their UI and pipe them into `RECOG_API_KEY`.

## Follow-up Work

- Enforce the bearer token via a FastAPI dependency and add pytest coverage for 401 responses.
- Emit structured audit logs on auth failures so operators can detect misconfiguration.
- Document a rotation playbook alongside the deployment runbooks once multiple environments are live.
