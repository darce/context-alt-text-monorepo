# Lane B — AUTH-02 + AUTH-04 + WEB-17

## Result

Session gates `GET /x/{slug}`; seed bundles encode pre-scan (`seeded media`, `scanned_faces==0`, `people_count==0`); `POST /x/provision` is per-source 429-capped. Fix round fail-closes schema observe, observes tenant identities, and pins HTTP 401/409/410/429.

Final HEAD: recorded by the integrator after transplant.

## Commits

- `feat(demo): AUTH-02 session-gate GET /x/{slug}`
- `feat(demo): AUTH-04 encode pre-scan contract in seed bundle`
- `fix(demo): WEB-17 rate-limit demo provisioning`
- `fix(demo): AUTH-04 PreScanStateError naming`
- `fix(demo): AUTH-04 observe missing identity tables as zero`
- `fix(demo-http): W3-B-01 observe-fail-closed-schema`
- `fix(demo-http): W3-B-02 observe-tenant-media`
- `fix(demo-http): W3-B-03 limiter-fail-closed-default`
- `fix(demo-http): W3-B-04 unknown-bundle-410`
- `fix(demo-http): W3-B-05 cookie-jar-session`
- `fix(demo-http): W3-B-06 session-mint-lifecycle`
- `fix(demo-http): W3-B-07 pin-401-details`
- `fix(demo-http): W3-B-09 report-exception-name`

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

AUTH-02 skip session 401 → `assert 200 == 401` (`test_demo_router.py:91`). Restore: `git diff` clean vs post-impl.

AUTH-04 catalog `people_count=1` → `PreScanStateError: people_count must be 0, got 1`. Restore: `people_count=0`.

WEB-17 skip provision 429 → `assert 201 == 429` (`test_demo_router.py:367`). Restore: 429 raise kept.

## GREEN

Owned: `recognition/tests/api/test_demo_router.py` + `recognition/tests/service/test_demo_provisioning_service.py` — 38 passed.

Package slice: `recognition/tests/api` + `service` + `scripts` — `512 passed, 2 skipped in 183.22s`.

## Anchors (sed -n after last code commit)

- Loud fail: `demo_provisioning_service.py:103` `class PreScanStateError(RuntimeError):`
- Relation name: `demo_provisioning_service.py:159` `def _missing_relation_name(exc: BaseException) -> str | None:`
- Observe: `demo_provisioning_service.py:190` `async def observe_pre_scan_state(`
- Identity raise: `demo_provisioning_service.py:239` `f"tenant is not pre-scan: media_ids={media_present}, scanned_faces={faces}, people_count={people}"`
- Scalar invoked: `test_demo_provisioning_service.py:256` `assert fake.scalar_calls >= 2`
- Missing column: `test_demo_provisioning_service.py:311` `async def test_observe_pre_scan_state_missing_column_fails_closed() -> None:`
- Identities: `test_demo_provisioning_service.py:263` `async def test_observe_pre_scan_state_raises_when_tenant_has_identities(`
- RPM default: `demo.py:53` `_DEFAULT_PROVISION_RPM = 3`
- Provision RPM: `demo.py:56` `def _provision_rpm() -> int:`
- Cookie read: `demo.py:145` `def _session_token_from_request(request: Request) -> str | None:`
- Unknown bundle: `demo.py:165` `if isinstance(exc, (DemoEndedError, UnknownSeedBundleError)):`
- 409: `demo.py:195` `except PreScanStateError as exc:`
- Session mint catch: `demo.py:228` `except (DemoInstanceNotFoundError, DemoEndedError, UnknownSeedBundleError) as exc:`
- Cookie flags: `demo.py:237` `samesite="lax"` / `demo.py:238` `path="/x"`
- GET catch: `demo.py:257` `except (DemoInstanceNotFoundError, DemoEndedError, UnknownSeedBundleError) as exc:`
- 401 detail: `demo.py:265` `detail=exc.code.value,`
- Contract 409: `security.md:271` maps `PreScanStateError` to `409`
- Contract RPM: `security.md:281` `<= 0` or non-integer fall back to default 3
- 401 required: `test_demo_router.py:92` `assert resp.json()["detail"] == "session_required"`
- Cookie-only GET: `test_demo_router.py:134`
- 401 expired: `test_demo_router.py:174` `assert resp.json()["detail"] == "session_expired"`
- 401 invalid: `test_demo_router.py:189` `assert resp.json()["detail"] == "session_invalid"`
- Unknown bundle 410: `test_demo_router.py:194`
- Session 404: `test_demo_router.py:216`
- Zero RPM 429: `test_demo_router.py:349`
- Provision 409: `test_demo_router.py:384` `assert resp.status_code == 409`

## Fix round

### W3-B-01 — `fix(demo-http): W3-B-01 observe-fail-closed-schema`

RED:

```
FAILED ...::test_observe_pre_scan_state_missing_column_fails_closed - Failed: DID NOT RAISE <class 'sqlalchemy.exc.ProgrammingError'>
FAILED ...::test_observe_pre_scan_state_partial_missing_relation_fails_closed - Failed: DID NOT RAISE <class 'recognition.application.services.demo_provisioning_service.PreScanStateError'>
FAILED ...::test_demo_provision_pre_scan_violation_returns_409 - recognition.application.services.demo_provisioning_service.PreScanStateError: scanned_faces must be 0, got 1
```

GREEN: those three plus missing-tables path. Mutant `_count_or_missing` swallows all DB errors → `DID NOT RAISE ProgrammingError`. Restored.

### W3-B-02 — `fix(demo-http): W3-B-02 observe-tenant-media`

RED:

```
FAILED ...::test_observe_pre_scan_state_raises_when_tenant_has_identities - Failed: DID NOT RAISE <class 'recognition.application.services.demo_provisioning_service.PreScanStateError'>
```

GREEN: observe + provision raise on seeded `MediaIdentity` + labeled `IdentityCluster`; fake session `scalar_calls >= 2`. Mutant `return bundle.pre_scan` → DID NOT RAISE + `assert 0 >= 2`. Restored.

### W3-B-03 — `fix(demo-http): W3-B-03 limiter-fail-closed-default`

RED:

```
FAILED ...::test_demo_provision_zero_rpm_falls_back_to_default_and_429s - assert 201 == 429
```

GREEN: RPM=0 → default 3; 4th POST 429. Mutant `<=0` skip cap → `assert 201 == 429`. Restored.

### W3-B-04 — `fix(demo-http): W3-B-04 unknown-bundle-410`

RED:

```
FAILED ...::test_demo_router_unknown_seed_bundle_returns_410_without_tenant_data - recognition.application.services.demo_provisioning_service.UnknownSeedBundleError: unknown seed bundle 'retired-bundle'; known: acme, default
```

GREEN: GET and POST `/session` both 410, no tenant keys. Mutant drop catch → same UnknownSeedBundleError. Restored.

### W3-B-05 — `fix(demo-http): W3-B-05 cookie-jar-session`

New cookie-jar GET was GREEN on current flags (https TestClient). Mutant ignore-cookies in `_session_token_from_request`:

```
FAILED ...::test_demo_router_cookie_only_get_resolves_without_session_header - AssertionError: {"detail":"session_required"}
assert 401 == 200
```

Restored. `Set-Cookie` asserts `SameSite=Lax` and `Path=/x`.

### W3-B-06 — `fix(demo-http): W3-B-06 session-mint-lifecycle`

New tests GREEN on current mint. Mutant drop `resolve_demo`:

```
FAILED ...::test_demo_session_unknown_slug_returns_404_without_tenant_data - assert 201 == 404
FAILED ...::test_demo_session_expired_and_revoked_return_410_without_tenant_data - assert 201 == 410
```

Restored. Bodies carry no tenant keys.

### W3-B-07 — `fix(demo-http): W3-B-07 pin-401-details`

Pinned details GREEN. Mutant always-`session_required`:

```
FAILED ...::test_demo_router_expired_session_returns_401_without_tenant_data - AssertionError: assert 'session_required' == 'session_expired'
FAILED ...::test_demo_router_invalid_session_returns_401_without_tenant_data - AssertionError: assert 'session_required' == 'session_invalid'
```

Restored.

### W3-B-09 — `fix(demo-http): W3-B-09 report-exception-name`

AUTH-04 mutant line said `PreScanStateViolation`; production raises `PreScanStateError`. Corrected.

## Undone

- W3-B-08 deferred: public provision exposure policy / global spend cap; no auth or global cap added.
- Session and provision counters are in-process (single-worker); multi-worker needs a shared store.
- `POST /x/provision` never returns the raw API key; operator CLI still prints it once.
- Catalog `seeded_media_ids` stay strings; this service has no WP media table. Observe queries tenant `MediaIdentity.media_id` (int) and labeled clusters and raises if either is non-zero.
- `X-Demo-Session` is not added to CORS `allow_headers` (`api/main.py` out of ownership).
- No logout/revoke for a minted demo session; TTL expiry only.
- Partial-schema observe raises `PreScanStateError` (409 on provision); a missing *column* still surfaces as the original `ProgrammingError` (uncaught 500) — fail-closed, not mapped to 503.

## Canon cited

- TEST-15 — every finding mutated production and the named assertion went RED, then restored.
- TEST-06 — each new test was observed failing (or the specified mutant was) before GREEN.
- SECD-05 — RPM `<=0`/invalid and broken schema fail-safe to default cap / re-raise, not open.
- WEB-17 — unpriced `POST /x/provision` stays per-source 429-capped; cap cannot be disabled by env.
- SEC-08 — same surface sits in front of GPU spend; default RPM 3.
- WEB-31 — `GET /x/{slug}` and `POST /x/{slug}/session` still authorize on the server.
- WEB-10 — session cookie is `HttpOnly`+`Secure`+`SameSite=Lax`+`Path=/x`; cookie-jar GET now exercised.
- WEB-09 — session is cookie/header, never a URL param.
- WEB-29 — session tokens remain `secrets.token_urlsafe(32)`; store keeps `sha256(token)`.
- contract-before-components — `docs/workbay/contracts/security.md` updated in the same commits as 409/410/RPM fallback.
- fail-loudly-succeed-quietly — missing column / half-schema / identities existing fail loud; fresh empty tenant stays quiet.
