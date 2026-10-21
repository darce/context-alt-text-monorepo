# Tech Debt: SECPIPE-1 security is not encoded in the review pipeline

**Status:** deferred · **Owners:** this repo owns the policy half; Workbay owns the mechanism half ([upstream request](#links)) · **Origin:** SECAUDIT-1 close-out design review, 2026-10-21 (main `02d4cd0cf3c61a555bca5ee1dd27bd0dc0288510`)

## What is deferred

Security review here runs as periodic, hand-built audits: SECREV-1 in July ([`docs/assessments/security-review-prototype-wp-alt-context-2026-07-11.md`](../assessments/security-review-prototype-wp-alt-context-2026-07-11.md)) and SECAUDIT-1 in October. The per-branch review pipeline carries no security policy of its own. Six gaps:

1. **No protection model or threat model.** [`docs/workbay/contracts/security.md`](../workbay/contracts/security.md) is an auth-configuration contract. Its overview (line 10) still justifies API keys by "a single-tenant WordPress plugin context", while the service is multi-tenant and SECAUDIT-1's main fix class was tenant claims. No document names the assets, principals, trust boundaries, or the attack each control answers.
2. **No security review profile.** `scripts/review_pipeline.py` (Workbay-owned) already reads repo policy from the `landing:` block of [`harness-protocol.yaml`](../workbay/contracts/harness-protocol.yaml) (lines 592–602, blocking severities). No equivalent block tells a reviewer which paths are trust boundaries, which invariants must hold, or which canon families apply.
3. **Invariants exist only as tests.** SECAUDIT-1 added 9 `test_secaudit_*` regression files (tenant-claim 403, cluster-member ownership, GPU operator allowlist and others). Nothing maps invariant to test, so a reviewer cannot check a diff against them and a weakened one is not flagged.
4. **No Security lens.** The Multi-Lens Audit in [`branch-review-guide.md`](../workbay/rules/branch-review-guide.md) lists seven lenses (§ Lens Definitions, line 309). Security appears only as an escalation trigger (line 305) and in the mutation-proof rule for security tests (lines 177–179). No lens asks who can act across which boundary. Upstream's `security-audit` skill does not fill this: it is a periodic whole-repo audit, reads no repo policy, and is not in this repo's generated plugin.
5. **Dangling canon pointer.** Six generated Workbay skills (`branch-review`, `review-parallel`, `scope`, `investigate`, `auto-fix`, `incremental-implementation`) link `docs/workbay/rules/heuristics-canon.md`, which is absent here: `.gitignore:170` ignores `/docs/workbay/rules`, and the upstream payload stub was never materialized. Canon routing in reviews depends on `CLAUDE.md` and agent memory.
6. **Audit machinery is untracked.** The SECAUDIT-1 harness (DAG build, canon-row injection, frozen snapshot plus planted canary, gate) lives in `.task-state/secaudit1/*.py`. Productizing it locally would repeat [OPS-2](OPS-2-vendored-remote-agent-fork.md), a vendored fork drifting from upstream.

SECAUDIT-1's own residuals (Postgres role split, suite-wide hermetic test-DB guard `SECAUDIT-1-i3-telemetry-db-01`, SSRF DNS-rebinding residual, members normalizer 404→502) are SECAUDIT-2 follow-ups, not part of this item.

## Why deferring is safe

- SECAUDIT-1 merged with gate verdict MERGE and no open high. Its regression tests run in the normal suites.
- Runtime controls fail closed independently of review, so a missed review is not a single point of failure.
- No production users; exposure is the public demo.
- The profile (gap 2) needs a Workbay reader. Writing it before one exists gives a file nothing reads.

## Split and seam

Policy lives here; mechanism lives in Workbay. The seam is one versioned, schema-validated contract file that this repo writes and Workbay reads, failing closed when it is malformed (rg-008). This is the same pattern as the `landing:` block and `[tool.workbay.remote_test]` in `pyproject.toml` (decision 7777).

| Workbay (mechanism) | This repo (policy) |
|---|---|
| Profile reader and schema validation | Threat model: assets, principals, trust boundaries |
| Code-area detection mapped to canon families | Extra path triggers Workbay cannot detect (`infra/**`, face and embedding code) |
| Canon rows, cards and prior art injected into reviewer briefs | Invariants, each tied to a regression test |
| Security lens on every review that hits a trigger | Canary catalogue grown from real defects |
| Frozen snapshot plus planted canary; a missed canary marks the review unverified | Hermetic test env (blocked-port database URL) |
| Finding fields: rule ID, trust boundary, failure scenario | Accepted-risk deferrals, recorded in MCP |

Profile sketch (shape to follow whatever schema upstream ships):

```yaml
# docs/workbay/contracts/security-review-profile.yaml
version: 1
threat_model: docs/workbay/contracts/threat-model.md
triggers:
  - glob: infra/**
    families: [SECD, WEB]
invariants:
  - id: tenant-claim
    rule: query/header tenant_id must equal the key's tenant, else 403
    test: apps/prototype-description-service/recognition/tests/api/test_secaudit_tenant_query_claim.py
canaries:
  - file: apps/prototype-description-service/scene/interface_adapters/http/routers/gpu.py
    mutant: empty ACX_GPU_OPERATOR_TENANT_IDS lets every tenant in
hermetic_env:
  POSTGRES_DSN: postgresql+asyncpg://nodb:nodb@127.0.0.1:9/nodb
```

## Trigger for pickup

- **Threat model (gap 1):** before the next branch that adds a route, a principal, or a tenant-scoped query. It is useful to human and agent reviewers without any Workbay change.
- **Profile, invariant map and canaries (gaps 2, 3):** when upstream ships a profile reader.
- **Lens and canon pointer (gaps 4, 5):** arrive with the Workbay release; adopt on the next `workbay update`.

## Acceptance criteria

- `docs/workbay/contracts/threat-model.md` names assets, principals and trust boundaries, and for each boundary its control and test. The `security.md` overview describes the multi-tenant model.
- The profile validates against the upstream schema and carries only what Workbay cannot detect: extra triggers, invariants with test paths, canaries, hermetic env.
- Every `test_secaudit_*` file maps to a profile invariant.
- A branch touching a trigger path gets a security lens in its normal review, with no hand-built harness. A lens run that misses its planted canary is recorded as unverified.
- The canon pointer resolves, or the skills report it as unavailable.
- `.task-state/secaudit1/` scripts are archived once upstream lands the mechanism.

## Canon (v0.26.2)

- AGT-17 **Separate policy from mechanism** (The Art of UNIX Programming, ch. 1): the split itself.
- AGT-19 **Don't configure what you can detect** (The Art of UNIX Programming, ch. 10): the profile carries only undetectable facts.
- SECD-01 **State the protection model first** (Security Engineering, ch. 1) and SECD-07 **Threat-model before mechanism** (Security Engineering): gap 1 comes first.
- SECD-16 **Integrate security through delivery** (Accelerate, ch. 6): a lens in every review, not periodic audits.
- TEAM-06 **No permanent critical-path hand-off silos** (Team Topologies): no standing security gate.
- TEAM-04 **Single accountable ownership** (Team Topologies): one owner per half.
- SECD-06 **Independent defense in depth** (Security Engineering): lens, invariant tests and runtime fail-closed checks fail independently.
- CARD-08 Falsification and disconfirmers: the planted canary makes a review falsifiable.

## Links

- Upstream request: `agentic-protocol-monorepo/docs/upstream-requests/REQUEST-security-review-lens-reads-a-consumer-owned-security-profile-20261021.md`
- SECAUDIT-1 landing decisions 18884 (slice complete) and 18889 (landed on main).
