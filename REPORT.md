# Lane B — AUTH-02 + AUTH-04 + WEB-17

## Result

Session gates `GET /x/{slug}`; seed bundles encode pre-scan (`seeded media`, `scanned_faces==0`, `people_count==0`); `POST /x/provision` is per-source 429-capped.

Final HEAD: recorded by the integrator after transplant.

## Commits

- `feat(demo): AUTH-02 session-gate GET /x/{slug}`
- `feat(demo): AUTH-04 encode pre-scan contract in seed bundle`
- `fix(demo): WEB-17 rate-limit demo provisioning`
- `fix(demo): AUTH-04 PreScanStateError naming`
- `fix(demo): AUTH-04 observe missing identity tables as zero`

## TDD RED (verbatim)

AUTH-02 collection:

```
E   ImportError: cannot import name 'reset_demo_sessions_for_tests' from 'recognition.application.services.demo_provisioning_service'
```

AUTH-04 collection:

```
E   ImportError: cannot import name 'PreScanState' from 'recognition.application.services.demo_provisioning_service'
```

WEB-17 collection:

```
E   ImportError: cannot import name '_reset_provision_limiter_for_tests' from 'recognition.interface_adapters.http.routers.demo'
```

AUTH-04 missing-table observe (owned fixture):

```
FAILED ...::test_observe_pre_scan_state_missing_tables_count_as_zero - sqlalchemy.exc.OperationalError: (builtins.Exception) no such table: media_identities
```

## TEST-15 mutants (production mutated, suite RED, restored)

AUTH-02 skip session 401 → `assert 200 == 401` (`test_demo_router.py:84`). Restore: `git diff` clean vs post-impl.

AUTH-04 catalog `people_count=1` → `PreScanStateViolation: people_count must be 0, got 1`. Restore: `people_count=0`.

WEB-17 skip provision 429 → `assert 201 == 429` (`test_demo_router.py:262`). Restore: 429 raise kept.

## GREEN

Owned: `recognition/tests/api/test_demo_router.py` + `recognition/tests/service/test_demo_provisioning_service.py` — 28 passed.

Package slice: `recognition/tests/api` + `service` + `scripts` — `502 passed, 2 skipped in 204.48s`.

## Anchors (sed -n after last code commit)

- Cookie name: `demo_provisioning_service.py:34` `DEMO_SESSION_COOKIE = "acx_demo_session"`
- Catalog: `demo_provisioning_service.py:70` `SEED_BUNDLES: dict[str, SeedBundleContract] = {`
- Loud fail: `demo_provisioning_service.py:145` `raise PreScanStateError("seeded media must be present in the seed bundle")`
- `demo_provisioning_service.py:147` `raise PreScanStateError(f"scanned_faces must be 0, got {state.scanned_faces}")`
- `demo_provisioning_service.py:149` `raise PreScanStateError(f"people_count must be 0, got {state.people_count}")`
- Observe: `demo_provisioning_service.py:158` `async def observe_pre_scan_state(`
- Mint: `demo_provisioning_service.py:375` `def mint_demo_session(`
- Bind: `demo_provisioning_service.py:394` `def resolve_demo_session(`
- Provision RPM: `demo.py:53` `raw = os.getenv("RECOGNITION_DEMO_PROVISION_RPM", "3")`
- 429: `demo.py:60` `async def enforce_provision_rate_limit(request: Request) -> None:`
- HTTP provision: `demo.py:178` `async def provision_demo_instance(`
- Exchange: `demo.py:210` `async def mint_demo_slug_session(`
- Cookie flags: `demo.py:225` `httponly=True` / `demo.py:226` `secure=True`
- GET gate: `demo.py:251` `resolve_demo_session(_session_token_from_request(request), slug=slug)`
- 401: `demo.py:254` `status_code=status.HTTP_401_UNAUTHORIZED,`
- Contract: `docs/workbay/contracts/security.md:238` `## Public demo instance HTTP surface`
- `security.md:254` `3. Missing session → 401 {"detail": "session_required"}.`
- `security.md:275` `### Provision — POST /x/provision (WEB-17)`
- Anon GET: `test_demo_router.py:84` `assert resp.status_code == 401`
- Flood: `test_demo_router.py:262` `assert resp.status_code == 429`
- Invariant RED case: `test_demo_provisioning_service.py:204` `with pytest.raises(PreScanStateError, match="people_count"):`

## Undone

- Session and provision counters are in-process (same single-worker limit as existing `/x/*` IP limiter); multi-worker needs a shared store.
- `POST /x/provision` never returns the raw API key; operator CLI still prints it once.
- Seeded media IDs live in the bundle catalog; this service has no WP media table to insert into.
- `X-Demo-Session` is not added to CORS `allow_headers` (`api/main.py` out of ownership).
- No logout/revoke for a minted demo session; TTL expiry only.
- Cookie round-trip under `Secure` is not exercised on HTTP TestClient (header path is).

## Canon cited

- WEB-31 — `GET /x/{slug}` is a privileged read; slug-in-URL is not authorization; session is checked on the server (`demo.py:251`).
- WEB-17 — unpriced `POST /x/provision` is per-source rate-limited to 429 (`demo.py:60`).
- SEC-08 — same surface sits in front of GPU spend; provision RPM default 3 (`demo.py:53`).
- TEST-15 — each item mutated production and the named assertion went RED, then restored.
- contract-before-components — `docs/workbay/contracts/security.md:238` written in the same commits as the payload/endpoints.
- WEB-10 — session cookie is `HttpOnly`+`Secure` (`demo.py:225-226`).
- WEB-29 — session tokens are `secrets.token_urlsafe(32)`; store keeps `sha256(token)` (`demo_provisioning_service.py:375`).
- WEB-09 — session is cookie/header, never a URL param.
