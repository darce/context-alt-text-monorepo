# Decomposition — OB-8 (Infra / Host Observability + Alerting)

> The **Epic** slice added to launch-plan §14's OB group for the **host/infra observability plane** — distinct from OB-1..3 (PostHog product funnel) and OB-4/5 (Sentry app errors). Broken into **atomic** sub-slices, each with a self-contained end-state and a scoped verification.
> **Engineering heuristics v2** (cite in every slice): [`docs/strategy/engineering-heuristics.md`](../strategy/engineering-heuristics.md).
> **Co-owned with:** the E14 self-hosting epic (`docs/epics/v0.3.1/self-hosting-epic.md`) — host observability is operational hygiene for the self-hosted OCI stack, surfaced here because launch §9 says *no funnel, no launch* and the same discipline applies to the box serving the demo.
> **Source:** launch-plan §9 (the third observability plane) + the acx-backend console audit (decision `claude_oci_acx_backend_security_audit_20260710`).

---

## Why a distinct plane (do not fold into PostHog/Sentry)

Three observability planes, three consumers, three failure modes — keep them separate `[OBS-05]`:

| Plane | Tool | Consumer | Slices |
|---|---|---|---|
| Product funnel | PostHog | growth/operator | OB-1..3 |
| App errors/traces | Sentry | on-call/dev | OB-4/5 |
| **Host/infra** | OCI metrics + Cloud Guard + Notifications | operator/ops | **OB-8** |

Host alerting has different data (no product IDs), a different consumer (ops, not growth), and a different failure mode (the box, not the funnel). Merging it into the PostHog/Sentry slices would couple unrelated concerns.

---

## OB-8 sub-slices

| Sub-slice | End-state | Scoped `TEST_CMD` / verify | Heuristics | Deps |
|---|---|---|---|---|
| **OB-8a** Notifications topic + routing | An OCI **Notifications topic** with an email subscription; the Cost **Budget alert**, **Cloud Guard** findings, and **scheduled-maintenance events** all route to it. Thresholds live in OCI (budget/alarm config), not in app code. | a test publish reaches the confirmed email; the budget alert and a Cloud Guard finding both land in the topic | `[OBS-05]` (expose state, externalize policy), biz `[SEC-08]` (budget alerts vs denial-of-wallet) | — |
| **OB-8b** symptom alarms | OCI **alarms** page on *symptoms* — `/health` failure, 5xx-rate spike, TLS-cert expiry — routed to the OB-8a topic. A raw CPU/memory spike **alone does not page**. | forced `/health` failure fires an alarm to the topic; a synthetic CPU spike with healthy `/health` does **not** page | `[OBS-07]` (page on symptoms not causes), `[OBS-04]` (alarm = operator action) | OB-8a |
| **OB-8c** host agents + IAM fix | Enable **Vulnerability Scanning (VSS)** and **OS Management Hub Agent** on acx-backend; fix the IAM policy behind the observed `PublishTopProcessesMetrics NotAuthorizedOrNotFound` so patch state + top-process metrics flow. | a VSS scan report is produced; OS-Mgmt shows patch state; top-process metrics stop erroring | `[OBS-05]`, `[SEC-10]` (provenance/patch hygiene) | — |
| **OB-8d** stream freshness gate | A **freshness gate** on the critical telemetry streams (host metrics **and** the flywheel/funnel event pipeline): alert when an *expected* stream goes quiet, distinguishing "no events" from "capture broken." | stop the emitter → the gate fires within the window; a genuinely idle-but-healthy stream does not false-page | `[OBS-08]` (silence is not success) | OB-8a |

> **Boundary — NOT an OB-8 slice (two hats `[REF-05]`):** the **security-hardening instance recreate** (Shielded Instance: Secure Boot / Measured Boot / TPM; `is_pv_encryption_in_transit_enabled`) is *security hardening*, not observability. It is owned by `MAINT-oci-hardening-observability-20260710` / E14 and gated on a maintenance window (those launch-options are launch-time-only, not live-togglable). Its rationale is recorded in decision `claude_oci_instance_security_posture_20260710` `[ARCH-07]`. Do not bundle it into an OB slice.

---

## Sequencing

- **Phase 0 (alongside OB-1):** OB-8a + OB-8b — a Notifications topic and a symptom alarm on the **demo host** are cheap and stop the demo box falling over mid-pitch unseen. Land with the funnel.
- **Phase 1+:** OB-8c (host agents) and OB-8d (freshness gate) once there is real traffic whose silence would matter.

## Offload guidance

- **Straight-to-offload (atomic, clean verify):** OB-8a, OB-8b, OB-8c, OB-8d — each is one end-state + one scoped check.
- **Reasoning owner (Claude/operator):** the symptom-vs-cause alarm policy (`[OBS-07]`), which streams the freshness gate watches, and the plane-separation boundary above. **Junior/offload owner:** the atomic rows.
- Each brief = the row's End-state (objective) + its verify + a known-red baseline ("topic/alarm/agent/gate does not exist; check fails") + the cited heuristic IDs.
