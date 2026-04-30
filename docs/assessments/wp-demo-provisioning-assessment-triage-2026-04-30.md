# WP Demo Provisioning Assessment Triage

> **Date**: 2026-04-30
> **Task**: `ASSESSMENTS-WP-DEMO-TRIAGE-20260430`
> **Scope**: `docs/assessments/` triage for provisioning a WordPress server/site at `demo.altcontext.com`
> **Status**: Final

## Decision

Provision `demo.altcontext.com` only after the E15-3a LocalWP -> OCI round-trip gate passes. The assessment corpus points to one shortest path: managed/shared WordPress hosting, private operator admin access, ACX plugin configured against `https://api.altcontext.com`, seeded licensed demo media, and a public conversion page. Do not use the existing OCI backend VM for WordPress unless budget becomes an emergency constraint, and do not build public visitor upload/admin access for the first launch.

## Ordered Provisioning Task Queue

| Priority | Task | Source assessment(s) | Owner surface | Gate / exit evidence |
| --- | --- | --- | --- | --- |
| P0 | Finish E15-3a LocalWP -> OCI gate before spending on hosting. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md`, `e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md` | `docs/tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md` | Run log proves settings probe, Workbench scan, CORS rejection, 429, and local-read fallback. |
| P0 | Select a managed/shared WordPress host and record the decision. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md` | New `docs/tasks/15.0/E15-3-host-decision-record.md` or E15-3 slice note | Host meets WordPress.org PHP/MySQL/MariaDB/HTTPS requirements and E15-3 resource floor. |
| P0 | Provision `demo.altcontext.com` WordPress site. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md` | E15-3 | DNS/TLS works, WordPress is installed, admin is private, public page loads. |
| P0 | Install and configure the ACX plugin on the demo site. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md`, `wp-alt-context-cross-cutting-assessment.md` | E15-3 | Plugin ZIP installed, backend URL is `https://api.altcontext.com`, API key is stored server-side, settings probe succeeds. |
| P0 | Seed licensed demo media and rosters, then run the live Workbench scan. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md` | E15-3 | 5-10 provenance-tracked images and 3-5 identities exist; scan result is captured without exposing raw API keys. |
| P1 | Build the conversion landing page. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md` | E15-3 / content slice | First viewport explains value, includes proof screenshot/video, privacy/licensing note, and lead capture. |
| P1 | Add demo-ops hardening checks, but do not block host purchase unless E15-3a fails. | `wp-alt-context-cross-cutting-assessment.md`, `infailed-sql-transaction-*.md`, `e15-3a-br21-*.md` | Follow-on hardening task(s) | Bound risky request paths, preserve private admin-only model, and keep backend failure evidence visible. |
| P2 | Spec public guided upload only after Path A is live. | `public-demo-wp-plugin-launch-assessment-2026-04-30.md`, `wp-alt-context-cross-cutting-assessment.md` | E16 / follow-on epic | Separate public surface with nonce/CAPTCHA/rate limits; no wp-admin exposure. |

## Assessment Corpus Triage

| Assessment | Tier | Provisioning relevance | Disposition |
| --- | --- | --- | --- |
| `public-demo-wp-plugin-launch-assessment-2026-04-30.md` | P0 | Primary source for hosting choice, access model, demo content, conversion page, and immediate next steps. | Use as canonical assessment input for E15-3. |
| `e15-3a-br21-clustering-insert-statement-timeout-2026-04-23.md` | P0 gate context | Explains a prior E15-3a scan-roundtrip blocker. Current task plan says BR remediation shipped, so treat it as a regression checklist, not proof the gate is still blocked. | Keep linked from E15-3a evidence if the clustering path fails again. |
| `wp-alt-context-cross-cutting-assessment.md` | P1 hardening | Identifies plugin risks relevant to a public demo: private admin boundary, bounded iterations, retries, circuit breakers, UI error/empty states. | Feed post-launch or pre-launch hardening only where E15-3a evidence exposes user-visible failure. |
| `infailed-sql-transaction-investigation-2026-04-09.md` | P1 historical reliability | Captures the earlier backend session-lifecycle failure class. Important for demo reliability review, but superseded by later remediation/spec work. | Use as historical regression context, not as a provisioning blocker by itself. |
| `infailed-sql-transaction-persistent-after-slr-2026-04-10.md` | P1 historical reliability | Narrows auth transaction isolation risk after SLR work. Relevant if `/recognition/analyze` fails under demo traffic. | Keep as backend hardening reference; do not block WP host selection unless E15-3a reproduces it. |
| `clustering-pipeline-postgres-refactor-literature-2026-04-26.md` | P1 architecture | Supports backend timeout/circuit-breaker/phase-split reasoning. | Use for hardening tasks after E15-3a, not for host provisioning. |
| `pgcache-description-service-db-read-write-assessment-2026-04-30.md` | P2 performance | Suggests future projection read-model work; not needed for a small seeded demo. | Defer until production-like snapshot/delta read latency is measured. |
| `review-guide-hardening-source-crosswalk.md` | P3 process | May improve future reviews but does not affect WP server provisioning. | Ignore for E15-3 provisioning. |
| `e17-13-hoisted-surface-inventory.md` | P3 process | External agent/MCP package inventory; unrelated to demo hosting. | Ignore for E15-3 provisioning. |
| `agent-handoff-mcp-cli-vs-native-tools-investigation-2026-04-16.md` | Irrelevant | Agent tooling only. | Archive/ignore for this goal. |
| `dashboard-md-vs-txt-guidance-drift-investigation-2026-04-16.md` | Irrelevant | Agent dashboard guidance only. | Archive/ignore for this goal. |
| `review-runs-tool-bridge-gap-investigation-2026-04-16.md` | Irrelevant | Agent review tooling only. | Archive/ignore for this goal. |
| `e17-12-codex-skill-registration-discovery-2026-04-18.md` | Irrelevant | Agent skill registration only. | Archive/ignore for this goal. |
| `agent-skills-vs-spec-kit-evaluation.md` | Irrelevant | Agent methodology only. | Archive/ignore for this goal. |
| `skill-pattern-extraction-assessment.md` | Irrelevant | Agent skill extraction only. | Archive/ignore for this goal. |
| `superpowers-evaluation.md` | Irrelevant | Agent/tooling capability notes only. | Archive/ignore for this goal. |
| `agent-performance-cold-start-compaction-tree-layout-2026-04-23.md` | Irrelevant | Agent performance only. | Archive/ignore for this goal. |
| `parallel-reviews-and-autonomous-debug-assessment-2026-04-16.md` | Irrelevant | Agent workflow only. | Archive/ignore for this goal. |
| `README.md` | Index | States assessments are planning inputs, not active task plans. | Preserve. |

## Provisioning Sequence

1. Complete [E15-3a LocalWP -> OCI Backend Round-Trip Verification](../tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md). This is the spend gate.
2. Record host choice in a short E15-3 decision artifact: managed/shared WordPress host preferred; existing OCI VM rejected for first launch; Fly.io retained only as fallback.
3. Provision DNS/TLS and WordPress for `demo.altcontext.com`; keep wp-admin private.
4. Install the ACX plugin, configure `https://api.altcontext.com`, store the demo API key server-side, and run the settings probe.
5. Seed licensed media/rosters, run the Workbench scan, and capture proof assets.
6. Publish a conversion page with screenshot/video proof, privacy/licensing text, and lead capture.

## Explicit Non-Priorities For First Launch

- Public visitor upload, public recognition API, or shared wp-admin credentials.
- Co-hosting WordPress on the current OCI inference VM.
- PgCache, PG18 projection-cache work, or image-to-text/model work.
- Broad plugin refactors unless E15-3a reveals a direct demo-blocking failure.
