# Security Assessment — Remote Test-Gate + Tailscale Access Control (OCI VM)

> **Metadata**
> - **Date**: 2026-07-12
> - **Author**: Claude Fable 5
> - **Status**: active — action items open
> - **Scope**: the `gate`-user remote test-gate offload (workbay `WB-REMOTE-GATE-01`, merged to workbay main `d2a4105e`) **and** the tailnet policy file governing reachability to the OCI VM (`tag:oci-vm`, host `acx-backend.tail1a44b8.ts.net`).
> - **Heuristics**: IDs cited are verified against `github.com/darce/heuristics-canon` `lexicons/security.md` (fetched 2026-07-12): SEC-01, SEC-04, SEC-05, SEC-08, PG-01, WEB-16.

## Context

The OCI VM (`VM.Standard.A1.Flex`, 4 OCPU / 24 GB) hosts the dev backend + Postgres (host port 55432) and is tagged `tag:oci-vm` on the tailnet. To offload the laptop's test load, a remote test-gate design (`scripts/remote_gate.sh`, workbay repo) pushes HEAD over Tailscale SSH and runs `make` targets on the VM as an unprivileged, resource-capped `gate` user. This assessment records the concerns that the security/portability review passes surfaced about (A) the script/design and (B) — the load-bearing layer — the Tailscale ACL that gates who can reach the VM at all.

## Part A — Script/Design Concerns (`scripts/remote_gate.sh` @ workbay `d2a4105e`)

Core hardening verified real (systemd-run resource caps with live scope-spawn probe + nice/ionice fallback; home-wipe path closed via dir/slug validation + `$PWD != $HOME` refusal + clone sentinel before any `git clean`; flock serialization → exit 75; local target-charset validation before ssh; no `curl|sh`; SSH keepalives; 18 subprocess-driven smoke tests). Open items:

- **NG-1 (medium) — claim/code contradiction on host default.** Commit `d6cb23d2` re-baked `gate@acx-backend.tail1a44b8.ts.net` as the default host, reverting the earlier "host required / no baked-in address" fix; `Makefile:245` still documents HOST as required. The audit trail contradicts the code. [SEC-01] Fix: restore required-host, or correct the Makefile/commit claim.
- **NG-2 (medium) — hostgov admission hook is silently invisible.** The `WB-MEMGOV-01` admission hook (`workbay-hostgov probe` pre-make) no-ops when the CLI is absent, and `doctor` does not report the absence (unlike uv/make/systemd-run, which each get a MISSING line). Probe *errors* are also indistinguishable from memory-pressure defers (both exit 75). Fix: one `command -v workbay-hostgov || echo MISSING` in `doctor`; distinguish probe-error from defer.
- **Low — env-value validation asymmetry.** `REMOTE_GATE_ENV` metachar blocklist omits `"`, `'`, and bare `$VAR`; `WORKDIR`/`REMOTE_DIR` are path-shape-validated but not metachar-validated, yet all are interpolated into the remote shell string. No demonstrated escape (separators blocked), robustness only. [SEC-01]
- **Consumer HIGH — `test-integration` greenwashes without VM Postgres.** For `context-alt-text-monorepo`, the pg-marked suite skips (never fails) when the DB is unreachable/underprivileged (`recognition/tests/conftest.py:329-336`), so `make` exits 0 with the entire pg suite silently dropped. The gate host must run Postgres at `localhost:55432` with pgvector and a `context` role able to `CREATE DATABASE`. This is a provisioning prerequisite (runbook Phase 1), not optional. `doctor`'s `nc` probe surfaces reachability only — auth/extension failure still shows "reachable". [PG-01 adjacent]
- **Distribution.** `remote_gate.sh` is in zero workbay overlay/packaging manifests — manual copy per consumer today. Overlay distribution is an upstream packaging ask.
- **NG-5 (HIGH, latent distribution leak) — private OCI host baked into a would-be-distributable tool.** `scripts/remote_gate.sh:59` resolves `REMOTE_HOST` to a **fail-open default** of `gate@acx-backend.tail1a44b8.ts.net` when unset — a private tailnet address hardcoded in source. Empirically it does **not** leak today: the script, runbook, and address are absent from the shipped overlay payload (`packages/workbay-system/workbay_system/payload/`; `git grep acx-backend -- packages/**` → zero hits), so third-party `workbay install` receives neither the feature nor the address. But the generalization goal is to ship this as a workbay tool; the first commit that adds it to the payload ships the private host as every consumer's default, and the fail-open fallback means an unconfigured consumer pushes their HEAD to the author's VM. [SEC-04 least-privilege agency; SEC-06 don't ship what must stay private — both verified in canon] **Fix (two independent controls):** (1) *gate* — remove the baked default; unset host → hard error `exit 78`, no fallback (`REMOTE_HOST="${_env_host:-${REMOTE_GATE_HOST:-}}"; [ -n "$REMOTE_HOST" ] || { echo "remote-gate: host not configured"; exit 78; }`); strip the address from the runbook (placeholder), and add `.workbay/remote-gate.env` to the consumer `.gitignore` template. (2) *privatize* — keep `remote_gate.sh` out of the public `workbay-system` payload entirely (operator-only script, or a separate private overlay source via `workbay install --source`); host/dir/env live only in the consumer's private `.workbay/remote-gate.env`. Architecture: shipped tool = pure mechanism with zero host knowledge. **Owner: workbay `WB-REMOTE-GATE-01` session — out of bounds for this repo.**

## Part B — Tailscale ACL Policy Concerns (load-bearing)

The `gate`-isolation design is gated by the policy's `ssh` block but **not** by the network fabric. Findings, most severe first.

### B-1 (CRITICAL) — the `grants` wildcard nullifies the SSH design

```jsonc
"grants": [ {"src": ["*"], "dst": ["*"], "ip": ["*"]} ],
```

This grants every tailnet node full TCP reach to every other node on every port. The `ssh` rules govern **only** the Tailscale-SSH path; they do not restrict raw TCP. Consequences: the VM's OpenSSH (:22), **Postgres (:55432)**, the dev backend, and any other listener are reachable from every device/tag on the tailnet regardless of the `gate`/`ubuntu` split — and that split is bypassable by connecting straight to `ubuntu@`'s OpenSSH (a separate daemon from Tailscale SSH) or directly to the DB port. The SSH-layer isolation is refinement on an open fabric. [SEC-04 least-privilege agency; SEC-01 validate at every trust boundary]

**Fix:** replace the wildcard with explicit per-tag grants (default-deny). Grant only the flows that exist; never include :55432 in a peer-reachable grant. See the corrected policy below.

### B-2 (HIGH) — admin path grants promptless `root`/`ubuntu` on the production VM

```jsonc
{"action":"accept","src":["autogroup:admin"],"dst":["tag:oci-vm"],"users":["ubuntu","root"]}
```

Every admin device gets standing, unattended `root` on the prod-tagged host. One compromised/prompt-injected admin device = prod root with no interactive gate. [SEC-05 human-in-the-loop for destructive/irreversible actions; SEC-04]

**Fix:** downgrade the `ubuntu`/`root` admin path to `"action":"check"` (re-auth prompt on interactive admin). Scripts never use these users — they use `gate`, which stays `accept`. Drop `root` unless a concrete need exists; use `sudo` from `ubuntu` under audit.

### B-3 (HIGH) — CI gets the service-owning `ubuntu`, promptless

```jsonc
{"action":"accept","src":["tag:ci"],"dst":["tag:oci-vm"],"users":["ubuntu"]}
```

A CI runner compromise (untrusted PR code, poisoned action) yields the service-owning user on prod. [SEC-04; SEC-05]

**Fix:** point CI *test* runs at `users:["gate"]` (same isolated path as local gating). Keep an `ubuntu` grant only for the deploy job, scoped to a dedicated `tag:ci-deploy` and ideally `check`-gated or behind the existing GitHub-Environment reviewer.

### B-4 (MEDIUM) — `gate` accept rule is un-narrowed and posture-free

`src:["autogroup:member"]` lets any member device push to the gate; no device-posture requirement (OS/auto-update/stable client), no source-tag scoping. Acceptable solo; tighten before adding a second tailnet user. [SEC-01] Fix (optional): a `posture` requiring an up-to-date client and/or `src` scoped to a `tag:gate-client`.

### B-5 (MEDIUM) — no `tests` block; ACL edits ship unverified

The `tests` stanza is commented out, so policy edits ship with no allow/deny assertion — exactly how the `tag:acx-backend`→`tag:oci-vm` typo (which surfaced this review) slipped through. [SEC-01 — the policy is itself a trust boundary] Fix: assert member→`gate@tag:oci-vm` accepted, raw `:55432` denied, and (post-fix) CI denied `ubuntu@`.

### B-6 (LOW) — Postgres :55432 needs network-level confinement

Even after B-1, ensure nothing but VM-localhost (and the `gate` test role) reaches Postgres. No tailnet peer should reach that port. [PG-01; SEC-04] Fix: keep :55432 out of every peer grant; bind Postgres to localhost in compose and rely on pg_hba for the `gate_test` role.

### Corrected policy (default-deny fabric + SSH split)

> Verify SSH-grant syntax against the live tailnet before removing the wildcard; on the newer `grants` model, Tailscale-SSH may need the app-capability form rather than a bare `tcp:22` grant. Save one rule and keep an admin device connected before tightening, to avoid lockout. The `tests` port syntax varies by account — the assertions matter even if field names need adjustment.

```jsonc
{
    "tagOwners": {
        "tag:oci-vm":     ["autogroup:admin"],
        "tag:ci":         ["autogroup:admin"],
        "tag:ci-deploy":  ["autogroup:admin"]
    },
    "grants": [
        { "src": ["autogroup:admin"], "dst": ["tag:oci-vm"], "ip": ["tcp:22"] },
        { "src": ["tag:ci"],          "dst": ["tag:oci-vm"], "ip": ["tcp:22"] },
        { "src": ["autogroup:member"],"dst": ["autogroup:self"], "ip": ["*"] }
        // NOTE: no peer grant to tcp:55432 — Postgres stays VM-localhost only.
    ],
    "ssh": [
        { "action": "check",  "src": ["autogroup:member"], "dst": ["autogroup:self"],
          "users": ["autogroup:nonroot", "root"] },
        { "action": "accept", "src": ["autogroup:member"], "dst": ["tag:oci-vm"],
          "users": ["gate"] },
        { "action": "check",  "src": ["autogroup:admin"],  "dst": ["tag:oci-vm"],
          "users": ["ubuntu"] },
        { "action": "accept", "src": ["tag:ci"],           "dst": ["tag:oci-vm"],
          "users": ["gate"] },
        { "action": "accept", "src": ["tag:ci-deploy"],    "dst": ["tag:oci-vm"],
          "users": ["ubuntu"] }
    ],
    "tests": [
        { "src": "autogroup:member", "dst": "tag:oci-vm", "accept": ["tag:oci-vm:22"] },
        { "src": "tag:ci",           "dst": "tag:oci-vm", "deny":   ["tag:oci-vm:55432"] }
    ]
}
```

## Action Items (recommended order)

1. **B-1** — replace the `grants` wildcard with explicit per-tag grants (makes every other control meaningful).
2. **B-2 / B-3** — downgrade admin `root`/`ubuntu` to `check`; move CI test runs to `gate`, split deploy onto `tag:ci-deploy`.
3. **B-5** — add the `tests` block so ACL edits are verified on save.
4. **B-4 / B-6** — device posture on the gate rule; confirm :55432 has no peer reach.
5. **A / NG-1, NG-2, NG-5** — route back to the workbay `WB-REMOTE-GATE-01` session. NG-5 (distribution leak) is HIGH: fail-closed host default + keep the feature out of the public payload before any overlay-distribution of remote-gate.
6. **Consumer HIGH** — add VM Postgres provisioning (pgvector + `context` CREATE DATABASE role) to runbook Phase 1 before any bootstrap for `context-alt-text-monorepo`.

## Related

- Provisioning runbook draft (workbay-bound): `docs/runbooks/remote-gate-provisioning.md` (to be landed by the WB session; `tag:acx-backend`→`tag:oci-vm` corrected).
- Review passes: two-reviewer parallel (security/shell + portability/generalization) and a post-merge verification pass against workbay main `d2a4105e`; routing-downgrade recorded (handoff MCP unavailable during the session).
