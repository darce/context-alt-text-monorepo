# Lane A report — AUTH-01 + AUTH-03

Final HEAD: recorded by the integrator after transplant.

## Commits

- `fix(demo): AUTH-01 rotate wp-admin credential on bootstrap`
- `fix(demo): AUTH-03 split CI account from demo admin`

## AUTH-01

**RED** (test before impl):

```
FAIL bootstrap uses wp user update for rotation: expected .../infra/oci/demo/bootstrap-wp.sh to match /wp user update/
6 assertion(s) failed
```

**GREEN:** `bash infra/oci/demo/tests/test-credential-lifecycle.sh` → `all assertions passed`

Second bootstrap with a changed secret calls `wp user update` then re-checks; unchanged secret is a no-op (`UPDATE_CALLS=0`). Update or post-update verify failure exits 2.

**TEST-15 mutant:** `if wp_user_password_matches` → `if true` (always no-op). Suite:

```
FAIL changed secret calls wp user update once: expected 1, got 0
9 assertion(s) failed
```

Restore: production `git diff` clean vs pre-mutant tree; suite green.

Pins (sed after code commit):

- `infra/oci/demo/bootstrap-wp.sh:68` `wpcli wp user check-password`
- `infra/oci/demo/bootstrap-wp.sh:71` `converge_wp_user_password()`
- `infra/oci/demo/bootstrap-wp.sh:79` `wpcli wp user update ... --user_pass=`
- `infra/oci/demo/bootstrap-wp.sh:190` call on `$WP_ADMIN_USER` (outside first-install `if`)
- `docs/runbooks/key-management.md:151` rotation procedure (secret-store write, then apply)

## AUTH-03

**RED** (test before impl):

```
FAIL bootstrap reads WP_CI_USER: expected .../bootstrap-wp.sh to match /env_get WP_CI_USER/
19 assertion(s) failed
```

```
FAILED .../test_provision_demo.py::test_cli_help_documents_account_kinds - assert '--account' in "usage: provision_demo provision [-h] --label LABEL [--seed SEED]..."
FAILED ...::test_cli_provision_ci_requires_admin_user - SystemExit: 2
5 failed, 4 passed
```

**GREEN:** `bash infra/oci/demo/tests/test-ci-account-split.sh` → `all assertions passed`. `uv run --extra dev pytest recognition/tests/scripts/test_provision_demo.py` → `9 passed`. `make -n issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin` expands to `python -m scripts.provision_demo --account ci --admin-user ...`.

**TEST-15 mutant:** collision guard `if [[ "$ci_user" == "$admin_user" ]]` → `if false && ...`. Suite:

```
FAIL CI user equal to admin exits 2: expected 2, got 0
FAIL collision does not create a user: expected 0, got 1
2 assertion(s) failed
```

Restore green.

Pins (sed after code commit):

- `infra/oci/demo/bootstrap-wp.sh:47` `env_get WP_CI_USER`
- `infra/oci/demo/bootstrap-wp.sh:52` required-vars include `WP_CI_*`
- `infra/oci/demo/bootstrap-wp.sh:94` role `acx_ci`
- `infra/oci/demo/bootstrap-wp.sh:100` `--clone=subscriber`
- `infra/oci/demo/bootstrap-wp.sh:104` `cap add ... manage_options`
- `infra/oci/demo/bootstrap-wp.sh:110` `converge_wp_ci_account()`
- `infra/oci/demo/bootstrap-wp.sh:193` CI converge after admin
- `.github/workflows/deploy-demo.yml:217` refuse demo-admin identity
- `.github/workflows/deploy-demo.yml:226` `acx-demo-admin|admin`
- `.github/workflows/deploy-demo.yml:246-247` Playwright env values from `secrets.ACX_E2E_WP_CI_*`
- `apps/prototype-description-service/scripts/provision_demo.py:36` `AccountKind`
- `apps/prototype-description-service/scripts/provision_demo.py:43` `CI_RECOGNITION_QUOTA = 20`
- `apps/prototype-description-service/scripts/provision_demo.py:104` `resolve_account_issuance`
- `Makefile.d/demo-auth.mk:10` `issue-demo-ci-account:`
- `docs/runbooks/key-management.md:179` issuance table + documented `make` commands
- `docs/workbay/contracts/security.md:76` demo identity contract

rg-006: documented `make issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin` and `make provision-demo LABEL="Acme Gallery" SEED=default` both exist as written.

## Fix round

Final HEAD: recorded by the integrator after transplant.

| id | commit | RED | GREEN |
| --- | --- | --- | --- |
| W3-A-01 | `fix(demo-auth): W3-A-01 upload-files-cap` | `FAIL CI role gains upload_files...` / `FAIL walkthrough fails closed when selectCount is 0` / `FAIL first CI converge cap-adds twice ... expected 2, got 1` / `5 assertion(s) failed` | `bash infra/oci/demo/tests/test-ci-account-split.sh` → `all assertions passed` |
| W3-A-02 | `fix(demo-auth): W3-A-02 call-site-after-install-fi` | gate-trap: `FAIL admin+CI converge calls sit on non-comment lines after install fi: expected 1 1, got 0 1` ; comment-out: `expected 1 1, got 0 0` | both suites `all assertions passed` |
| W3-A-03 | `fix(demo-auth): W3-A-03 idempotent-cap-add` | `FAIL existing-role retry cap-adds twice: expected 2, got 0` / `FAIL cap-add failure on existing role exits 2: expected 2, got 0` / `4 assertion(s) failed` | `all assertions passed` |
| W3-A-04 | `fix(demo-auth): W3-A-04 make-n-and-cap-add-count` | comment-only recipe: `FAIL make -n issue-demo-ci-account expands --account ci (non-comment)` / `2 assertion(s) failed` | `ok   make -n issue-demo-ci-account expands --account ci (non-comment)` + `all assertions passed` |
| W3-A-05 | `fix(demo-auth): W3-A-05 refusal-persists-nothing` | provision-then-raise: `FAILED ...test_cli_provision_ci_requires_admin_user - assert 1 == 0` / `FAILED ...test_cli_provision_ci_rejects_admin_collision - assert 1 == 0` / `3 failed, 6 passed` | `uv run --extra dev pytest recognition/tests/scripts/test_provision_demo.py -q` → `9 passed` |
| W3-A-06 | `fix(demo-auth): W3-A-06 ci-identity-guard` | `FAIL workflow refuses empty CI pass` / `FAIL workflow CI denylist is case-insensitive` / `FAIL workflow documents CI_USER must equal VM WP_CI_USER` / `3 assertion(s) failed` | `all assertions passed` |
| W3-A-07 | `fix(demo-auth): W3-A-07 ci-collision-email-converge` | `FAIL case-insensitive CI user collision exits 2: expected 2, got 0` / `FAIL CI email colliding with admin email exits 2: expected 2, got 0` / `FAIL create path verifies password via check-password: expected 1, got 0` / `FAIL existing CI user email is converged: expected 1, got 0` / `8 assertion(s) failed` | `all assertions passed` |

TEST-15 (one production mutant each; restore `git diff` clean on production):

- W3-A-01 skip `cap add upload_files` → `expected 2, got 1` + grep miss
- W3-A-02 gate-trap + comment-out call sites → `expected 1 1, got 0 1` / `got 0 0`
- W3-A-03 early-return on role-exists → `existing-role retry cap-adds twice: expected 2, got 0`
- W3-A-04 `# --account ci` in makefile recipe → make -n non-comment miss
- W3-A-05 provision-then-raise → `assert 1 == 0` DemoInstance count
- W3-A-06 drop empty `CI_PASS` + case-fold → empty-pass + `tr` grep miss
- W3-A-07 `"$ci_user" == "$admin_user"` (case-sensitive) → `case-insensitive CI user collision exits 2: expected 2, got 0`

Pins (sed after last code commit):

- `infra/oci/demo/bootstrap-wp.sh:105` `cap add ... manage_options` after exists-or-create
- `infra/oci/demo/bootstrap-wp.sh:112` `cap add ... upload_files`
- `infra/oci/demo/bootstrap-wp.sh:132` case-insensitive username collision
- `infra/oci/demo/bootstrap-wp.sh:136` case-insensitive email collision vs admin
- `infra/oci/demo/bootstrap-wp.sh:148` existing-user email read
- `infra/oci/demo/bootstrap-wp.sh:161` post-create `converge_wp_user_password`
- `infra/oci/demo/bootstrap-wp.sh:215` first-install `fi`
- `infra/oci/demo/bootstrap-wp.sh:219` admin converge after that `fi`
- `infra/oci/demo/bootstrap-wp.sh:222` CI converge with `$WP_ADMIN_EMAIL`
- `.github/workflows/deploy-demo.yml:228` empty `CI_PASS` refuse
- `.github/workflows/deploy-demo.yml:232` `tr '[:upper:]' '[:lower:]'`
- `apps/prototype-wp-alt-context/tests/e2e/evidence/demo-walkthrough.spec.ts:166` `selectCount === 0`
- `apps/prototype-wp-alt-context/src/api/class-api.php:394` `current_user_can( 'upload_files' )`
- `apps/prototype-description-service/scripts/provision_demo.py:121` `resolve_account_issuance` before `provision_demo`
- `apps/prototype-description-service/recognition/tests/scripts/test_provision_demo.py:24` row-count helper
- `docs/workbay/contracts/security.md:85` CI_USER must equal VM `WP_CI_USER`

## Undone

- `infra/oci/demo/.env.example` not updated (outside ownership); operators must add `WP_CI_*` from the runbook before the next bootstrap or it exits 2.
- Playwright `auth.setup.ts` still reads `ACX_E2E_WP_ADMIN_*` names (outside ownership); split is secret-value + workflow map only.
- `docs/runbooks/deploy-demo-cicd.md` still lists `ACX_E2E_WP_ADMIN_USER/PASS` as the smoke secrets (outside ownership) — runbook drift vs workflow.
- `acx_ci` still holds `manage_options` (plugin admin pages require it). Not administrator, but not a tiny cap set; shrinking further needs PHP capability changes (outside ownership).
- `/Makefile.d` is gitignored; `demo-auth.mk` was force-added so the documented target survives transplant.
- Live demo VM is not rotated here; first apply after transplant must populate `WP_CI_*` and GitHub `ACX_E2E_WP_CI_*` (two-key: store write then bootstrap/deploy).
- WEB-17 login rate-limit not added; Caddy `rate_limit` remains the deferred-hardening comment (stock image has no module).
- Dual-control is procedural (secret-store write ≠ apply), not a two-person GitHub Environment reviewer gate (free plan).
- `scripts/test_e15_28_demo_bootstrap.py::test_caddy_demo_vhost_blocks_xmlrpc_without_nonstock_directives` IndexError is pre-existing Caddyfile parse, not this lane. Bootstrap artifact assertions in that file still pass.
- W3-A-08 Makefile.d relocation, W3-A-09 operator secret provisioning, W3-A-10 ownership ack: deferred by brief.
- Workflow documents `ACX_E2E_WP_CI_USER` must equal VM `WP_CI_USER` but cannot read the VM secret from GitHub Actions; equality is operator procedure plus denylist, not a two-store compare.
- Email collision is vs `WP_ADMIN_EMAIL` only, not vs other WP users' mailboxes.
- Demo walkthrough empty-media fail is a spec assertion; this lane did not run Playwright against the live demo.
- `acx_ci` now also has `upload_files`; still not a tiny cap set (`manage_options` remains required for settings/scan REST).

## Canon cited

- **SEC-06** — passwords stay in the VM secret file / GitHub Environment; runbook forbids prompt/ticket paste.
- **WEB-16** — no demo passwords committed; tests use mock store values; stdout of provision still prints the API key once by design (hash-only in DB).
- **WEB-17** — checked; this slice does not add wp-login rate limits (existing Caddy xmlrpc 403 only).
- **least-privilege-blast-radius** — CI WP user is not the admin login; CI API quota 20 vs viewer 200; role is subscriber clone + `manage_options`, not `administrator`.
- **dual-control-two-keys** — rotation is two acts: secret-store write, then bootstrap/deploy apply. Either alone does not complete revoke.
- **fail-loudly-succeed-quietly** — rotation/collision/missing-CI-secret failures exit non-zero with ERROR; unchanged secret is a no-op.
- **TEST-15** — each item: production mutant turned the suite red; restore re-greened.
- **fail-loudly-succeed-quietly** — empty CI pass, cap-add failure, email/user collision, and empty walkthrough media all exit/fail; unchanged secret is still a no-op.
- **least-privilege-blast-radius** — `acx_ci` stays subscriber clone; added only `upload_files` required by workbench media REST, not `administrator`.
