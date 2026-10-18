# FEBT-1 lane f1a (red-http) report

Gates landed: FEBT1-W2C-09, FEBT1-W2C-08. W2C-13/W2C-14 out of this pass.
Tests: 32 → 34 (33 pass + 1 expected fail). Production files untouched.

## W2C-09 DEFAULT_FETCH_TIMEOUT_MS pin
- Test: `expect(DEFAULT_FETCH_TIMEOUT_MS).toBe(300_000)` + `advanceTimersByTimeAsync(300_000 - 1)`
- MUTANT W2C-09: 300_000→60_000 → RED: `expect(DEFAULT_FETCH_TIMEOUT_MS).toBe(300_000);`
- Commit: `69e1ba5881f6393ae28c18dc44d13f2c28671964`

## W2C-08 HTTP-date Retry-After
- Future HTTP-date 503: `retryAfterSeconds === 30`. Past date: `it.fails` (FEBT1-W2A-03 / F2).
- MUTANT W2C-08: HTTP-date branch return undefined → RED: `expect((error as HTTPError).retryAfterSeconds).toBe(30);`
- Commit: `d1b8cd8af4346fc375b57f426ca09192c6432265`

Canon: TEST-06, TEST-15, TEST-17; verify-assertion-can-fail.
