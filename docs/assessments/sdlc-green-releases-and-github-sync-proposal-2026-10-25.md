# Green releases and current GitHub publishing

Status: Draft proposal for Daniel Arcé, 25 October 2026. Reviewed specifications and task plans are required before implementation. Current implementation anchors were checked against main `77f7910262c0de06c29305dd9e85c7024766f6f1`.

Move heavy validation to isolated VM jobs, automate routine reviews and merges, and promote one verified release artifact through environments. Ask Daniel to decide consequential changes, with the affected sections and evidence attached. Keep GitHub synchronized with what actually passed and deployed.

## Resolve the inherited blockers

PR [#7](https://github.com/darce/context-alt-text-monorepo/pull/7) has passing focused coverage but inherited release blockers. Its base and head reproduce the same 610 ESLint violations against a baseline of 69, and 369 tracked formatting failures. Eight Linux CI harness failures also reproduce on main. The architecture workflow can print a success summary after an earlier failure. Focused passing tests do not substitute for required gates. Existing audit records are `QA-PR7-CI-001` and `OPS-DEPLOY-001`.

Main currently has no branch protection or rulesets; automatic merge and branch deletion are disabled. Historical dev/demo failures remain useful evidence. Restore the release path and verify present runtime acceptance before unattended promotion.

The remote gate reports four cores and approximately 14 GiB of available host memory. Its doctor exits successfully while reporting no declared workdir gate preflight. Available memory is not a job allocation. Require positive evidence for toolchains, authenticated database access, extensions, collection and required services. The [remote gate runbook](../runbooks/remote-test-gate.md) contains the corrected Postgres arrangement and required-PG behavior.

## Human attention goes to consequential changes

Classify behavior and dependency changes using trusted policy from the base revision. Filenames and model confidence cannot authorize merges. Unknown scope, disagreeing reviewers or incomplete evidence holds the change.

| Change                                | Automatic path                                                                                    | Human decision                                                                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Docs, formatting and generated output | Independent review and applicable checks; generation matches an approved source                   | Changed legal claims, public promises or product intent                                                            |
| Tests and ordinary fixes              | Stronger coverage, refactors and fixes within approved acceptance contracts; mandatory gates pass | Weaker assertions, removed coverage, skips, changed business goldens or expanded behavior                          |
| Dependencies                          | Approved patches with unchanged permissions, licenses and supported contracts                     | New authority, material supply chain risk, license obligations or breaking behavior                                |
| Security                              | Maintenance preserving the approved protection model and invariants                               | Auth, tenancy, object ownership, RLS, SSRF boundaries, secret access, IAM or runner privileges                     |
| Data and recovery                     | Reversible operations under approved retention rules, verified custody and no live owner          | Destructive migrations, new retention rules, loss of recovery evidence, key custody or history rewrites            |
| Money and resources                   | Provisioned CI capacity within approved limits                                                    | New financial transactions, billing/tax/credit behavior or expanded GPU spend/quotas                               |
| Models and privacy                    | Reproduction under an approved evaluation/deployment contract                                     | Biometric use/enrollment, face thresholds, privacy scope, model/data clearance or quality claims                   |
| Release and publishing                | Routine tags/assets, dev/demo and qualified reversible production patches                         | Gate-policy changes, initial production automation, irreversible effects, incompatible rollback or gate exceptions |

Billing remains governed by [ADR-014](../adrs/ADR-014-payment-processor-merchant-of-record-selection.md): standard Stripe direct plus Clerk, with AltContext's seller and manual tax responsibilities.

Each human request contains one decision, the consequential hunks and necessary context, before/after behavior, affected users/resources, independent findings, positive and negative test evidence, and recovery steps. Bind approval to base/head, policy version and artifact digest. Material changes invalidate approval; the next request highlights the new consequential difference. A solo owner can authorize a trusted SHA-bound status/dispatch without needing to approve their own PR through GitHub's review button.

Successful routine work produces a digest. Queue contention stays queued. Notify once per decision or unresolved incident, updating the same thread. New financial, destructive or irreversible acts require a specific human decision before execution; broad policy approval does not confer unrestricted authority.

## Trusted reviews and merges

Use remote Claude Haiku 5.5 for bounded classification, primary-source fetching and evidence assembly. It has no merge, deploy, production-secret or deletion authority. An independent reviewer checks correctness and security against changed contracts and relevant canon rows. Authors cannot attest their own review. Treat fetched text and PR content as untrusted input.

Make security an actual review lens. [SECPIPE-1](../tech-debt/SECPIPE-1-security-not-encoded-in-review-pipeline.md) identifies the stale tenancy contract, absent protection model, missing invariant-to-test mapping and missing profile reader. WorkBay owns the generic schema/profile reader and review mechanism; this repository owns threat modeling, invariants, mapped tests and escalation policy. Verify the upstream capability and schema before configuring it. Adding YAML alone provides no enforcement.

Protect main with required checks from trusted producers, strict up-to-date validation, blocked force pushes and no routine bypass. Incoming PRs cannot replace their own classifier, test denominator, receipt validator or approval mechanism. Policy changes take the human path.

Use a serialized merge controller with a repository-scoped GitHub App, expected PR head and freshly checked base; rerun validation when main advances. Branch protection enforces readiness independently of the controller. This personal repository is not eligible for GitHub's native merge queue: it requires organization ownership under the documented availability rules. If ownership changes, adopt the native queue with `merge_group` validation. [GitHub merge queue documentation](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue).

Use narrowly scoped App tokens for automation events that must start follow-on workflows, or explicit trusted dispatch. `GITHUB_TOKEN` pushes do not trigger ordinary downstream workflows, and its PR creation/update events can require a person to start resulting runs. Keep job permissions minimal. [GitHub token documentation](https://docs.github.com/en/actions/concepts/security/github_token).

## VM validation and trustworthy green checks

Extend existing `scripts/remote_gate.sh` and WorkBay lifecycle mechanisms. Start with one heavy job on the measured four-core VM. Preserve memory admission, BLAS caps, committed-source execution, clone locks, collection receipts and the whole-run deadline covering checkout through cleanup. Measure before increasing concurrency.

Run Python, JavaScript, PHP, formatting, architecture, Linux WordPress integration and headless Playwright remotely where dependencies permit. GPU evaluation uses its separately budgeted worker. Retain macOS LocalWP smoke tests for changes requiring host integration; laptop localhost ports are not VM endpoints. Add platform compatibility checks according to the supported release contract.

Keep fork/untrusted jobs on GitHub-hosted runners or disposable isolated VMs. Trusted orchestration can dispatch admitted internal jobs to isolated VM sandboxes. Resource caps and an unprivileged login do not isolate job code from that user's credentials, neighboring services, host sockets or cloud metadata. GitHub cautions against persistent self-hosted runners for public repositories. [GitHub secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).

Verify effective network/identity isolation against the [existing security assessment](current/remote-gate-oci-tailscale-security-assessment-2026-07-12.md); its historical findings require current verification. Prefer a dedicated CI VM if the shared host cannot demonstrate isolation. Separate test, review, merge and deployment identities. Test jobs receive disposable databases and no production credentials, agent OAuth files, host Docker socket or instance-principal access. A trusted outer controller signs receipts; job-generated JSON cannot certify itself.

Every required job reports source identity, lock/toolchain digests, command/profile, expected and actual collection, outcome and evidence location. Full suites and narrowed integration profiles have distinct expected scopes. Missing preflight, unexpected skips, stale evidence, cancellation, timeout, refusal and absent receipts cannot become success. Fix the unconditional success summary.

Busy/memory refusals queue with bounded backoff. Separate infrastructure failures from test failures. Proposed limits are one infrastructure retry and two repair attempts before escalation, preserving original failures. Cache keys bind dependency/toolchain identity; shared mutations have exclusive ownership. Test jobs cannot uninstall shared tool runtimes.

## Publishing and reconciliation

The proposed sequence is:

```text
PR → trusted classification → VM checks and independent review
   → human decision when required → serialized merge
   → release build from actual merged main SHA
   → dev/demo acceptance → eligible production canary
   → reconcile GitHub and running artifacts
```

Premerge builds validate the candidate. After merge, build the release artifact once from the resulting main SHA, verify it, then promote the same digest across environments. Its manifest binds Git tree/SHA, version, locks, platform/toolchain, collection, review/policy/canon versions and artifact digests. The old PR head cannot stand in for the merged release.

For WordPress, promote the verified ZIP and check installed version and bundle digest, activation, critical REST/admin paths and user-visible behavior. Preserve the previous compatible ZIP and recovery procedure. Extend the [LocalWP release runbook](../runbooks/localwp-plugin-release.md) and [demo deployment runbook](../runbooks/deploy-demo-cicd.md). Backend and portal deployments also verify running artifact identity.

Dev/demo can publish automatically after acceptance. Production automation begins after Daniel approves the operating envelope and rollback rehearsal. Subsequent reversible changes within that envelope can promote automatically. Canary checks require fixed error/latency thresholds, an observation window and sufficient traffic or synthetic coverage. Missing observations hold promotion. Incompatible database changes block application-only rollback; live data is not automatically restored.

Lease deployments per environment, bind the expected previous artifact, and make operations idempotent. Inspect live state after ambiguous timeouts before retrying. New releases queue once deployment starts instead of cancelling an in-progress promotion.

Reconcile after events and on a proposed 15-minute schedule: compare PR/check evidence, main, tags/assets, desired environment artifact and observed runtime digest. Record success after live acceptance and preserve failed historical records. A durable outbox retries GitHub publishing after API outages without redeploying. Proposed freshness targets are five minutes after verified changes and 15 minutes for reconciliation; alert on persistent drift.

Prevent attribution recurrence with a shared author/committer allowlist, case-insensitive agent coauthor-trailer validation, composed local hooks and a trusted required CI check. Client attribution opt-outs help; CI enforces the policy. Keep agent provenance in review evidence. Semantic prior art `UXW2-1`, decision 5681, showed a case-sensitive single-workflow scrub missed Cursor trailers. After clean history, contributor-widget caching follows GitHub's refresh process and then Support if needed. [GitHub contributor refresh guidance](https://docs.github.com/en/repositories/viewing-activity-and-data-for-your-repository/viewing-a-projects-contributors#contributor-data-is-stale-after-history-changes).

## Disk and worktree lifecycle

Place heavy new worktrees, caches and disposable output on the VM or Butter. Check each candidate's resolved filesystem/device; directory totals can include existing external links. A proposed 15 GiB internal free-space floor pauses new heavy local work and starts bounded reclamation. Retention/deletion policy changes require human review.

Join Git proof with WorkBay task/lane ownership and Orca sessions. An ancestor of current main is one condition. Require a clean checkout, inspection of ignored content, no active/unknown owner or terminal, retained receipts and verified backup. Squash merges and rewritten history need mapped tree/patch proof. Preserve unique work through review or salvage PRs. Reconcile stale ownership with its owner; age alone does not authorize deletion.

Use per-job leases, bounded retention and closed-file checks for temporary output. Preserve frozen benchmark evidence and shared/native ledgers. Relocate closed historical indexes with verified custody and path-preserving links. Reap abandoned Git temporary packs only after stable metadata, no holder/writer, verified backup and Git's garbage classification. Ordinary pack deletion, aggressive pruning and live database vacuuming are separate operations.

On 25 October, 52 abandoned Git temp files held 4,309,458,329 bytes, and 31 closed indexes held 540,737,536 internal bytes. Both have verified Butter custody; indexes remain registered and queryable. Source worktrees were preserved. Free-space observations include concurrent activity and cannot precisely attribute relief to one actor.

## Implementation order and acceptance

| Order | Owner and deliverable                                                                               | Completion evidence                                                                                                                     |
| ----- | --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Repository maintainers restore required CI/deployment contracts                                     | Green mandatory main suites; injected failures make aggregate red; missing DB/preflight/collection cannot pass; no raised debt baseline |
| 2     | WorkBay supplies profile/receipt mechanisms; repository supplies protection model and invariant map | Capability/schema checks, negative security canaries and consumer acceptance; no duplicate vendored mechanism                           |
| 3     | CI owner qualifies VM isolation, resources and authentication                                       | Real authenticated bounded job; production-secret/network denial; admission, timeout and cleanup receipts                               |
| 4     | Owner enables protection and trusted review/merge control, first in observation mode                | High-risk, changed-policy, stale-base/head, missing-check and forged-receipt fixtures hold; eligible low-risk PR completes unattended   |
| 5     | Release owner adds artifact promotion and reconciliation                                            | Merged SHA matches artifact/live installation; demo acceptance and rollback rehearsal; API retry cannot duplicate deployment            |
| 6     | Daniel approves production and retention envelopes                                                  | Exact scope, fixed canary thresholds, recovery limits and escalation examples; reconciliation/reclamation follow approved rules         |

Repository policy belongs here; generic execution/review/reclamation mechanism belongs in WorkBay. Specifications must name existing functions and proposed new interfaces before implementation. Production automation depends on the relevant earlier evidence.

## Canon and evidence

The pinned **heuristics canon v0.26.2** was used, with relevant lexicon, principle, source and reasoning-card digests verified.

| Rule and source                                                                                                         | Decision supported                                                                  |
| ----------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Architecture hoisting [ARCH-13], _Just Enough Software Architecture_, ch. 2                                             | Enforce sole-author, required-check and deployment-authority policies structurally  |
| Separate policy from mechanism [AGT-17], _The Art of UNIX Programming_, ch. 1                                           | Separate consumer risk policy from WorkBay execution/review                         |
| State the protection model first [SECD-01], _Security Engineering_, ch. 1                                               | Define falsifiable authority/tenancy invariants before claiming secure automation   |
| Least-privilege agency [SEC-04] and Human-in-the-loop gate [SEC-05], _The Developer's Playbook for LLM Security_, ch. 7 | Limit agent tools and require scoped human decisions for consequential side effects |
| Prove the green can go red [TEST-15], _The Pragmatic Programmer_, ch. 9                                                 | Inject failures into aggregates, security canaries and receipt checks               |
| Absolute standards against eroding goals [OBS-11], _Thinking in Systems_, ch. 5                                         | Keep fixed quality bars instead of promoting current debt into the threshold        |

Boundary/measurement cards require policy-to-control mappings and independently owned denominators. High-impact/least-privilege cards require separate authorizers and small grants. License-provenance checks apply when model/data clearance changes; they do not imply general license inheritance.

Evidence is retained under `/Volumes/Butter/CodexEvidence/pr7-ci-canon-20261025/` and `/Volumes/Butter/CodexEvidence/sdlc-publishing-proposal-20261025/`: baseline audits, remote readiness, authenticated Haiku 5.5 research, canon digests, reaper inventories, custody manifests and Orca coordination receipts. Haiku's conclusions were reviewed: native queue eligibility was checked directly, unchanged debt does not override mandatory green gates, and routine releases need not all consume human attention.
