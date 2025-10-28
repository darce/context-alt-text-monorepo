# Backend ↔ Frontend Integration Tasks

Sits alongside `tasks.md`. Tracks the remaining work to wire the FastAPI
recognition service to the WordPress plugin.

## Recognition Service Hardening
- [ ] Authentication/rate limiting for all `/api/v0/*`
- [ ] Gate roster mutations (write endpoints should require auth)
- [ ] Publish OpenAPI spec (replace reliance on JSON fixtures)
- [ ] Benchmarks + alerting (Exp F/F roadmap requirements)
- [ ] CI executes `pytest tests/integration/test_api_endpoints.py`

## WordPress Plugin Integration

### Config + Client
- [ ] Persist backend URL/API key in admin settings
- [ ] REST client calling `POST /api/v0/embeddings` with base64 payloads
- [ ] Retries + error mapping (roadmap requirement)

### Roster Management
- [ ] `POST /api/v0/roster` upsert (name, embedding, metadata)
- [ ] `POST /api/v0/roster/{id}/embeddings` for reference images
- [ ] Display stats via `GET /api/v0/roster` or `/roster/stats`

### Recognition Flow
- [ ] Trigger `POST /api/v0/analyze-scene` for selected media
- [ ] Show `/service/info` & `/health` in diagnostics

### Testing
- [ ] Mirror backend fixtures in PHP contract tests

### Next Actions
- [ ] Implement full client for `/api/v0/{embeddings, roster, analyze-scene, service/info, health}`
- [ ] Surface backend URL/API key fields in UI
- [ ] Add plugin-side fixtures/tests for backend JSON contracts
- [ ] (Optional) API-key auth + OpenAPI document for client integrations
