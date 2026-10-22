# AuraFace production endpoint access for tenants

**Status:** Deferred tech debt, registry item **#31**.
**Recorded:** 2026-10-20.
**Priority:** Before onboarding tenants to production AuraFace.
**Owners:** Deployment, recognition, and tenant-onboarding owners; assign named owners when promoted to an implementation task.

## Problem

`https://auraface.api.altcontext.com` is advertised by a configured Caddy route but has no observed production AuraFace upstream. On 2026-10-20, `/health`, `/ready`, and `/health/detailed` returned HTTP 502. The active route targets `prod-auraface-api:8000`; that name cannot resolve inside Caddy. The inspected VM contains only the development AuraFace API, worker, database, environment directory, and network.

Tenants cannot authenticate or run recognition through the production endpoint. This is a deployment and onboarding gap, distinct from recognition accuracy or production model-quality qualification. A reserved hostname or successful TLS connection does not establish tenant access.

## Current local workaround

The operator selected `https://auraface.dev.altcontext.com` for the LocalWP site at `http://localhost:10033` on 2026-10-20. Its effective WordPress endpoint was switched from the production hostname. Development `/health` returns HTTP 200.

The site now has its own Clerk development account, freshly claimed tenant, and portal-issued API key. WordPress **Check health** authenticated against development `/health/detailed` on 2026-10-20 at 21:06 UTC and returned `connected`, HTTP 200, and `tenant_paired: true`. Tenant `3d0495c8-c27d-46ce-8837-4dfee0b5c6c2` owns key `4ee87c65-16f4-4b35-a5e9-9a0a4dbab650` (no expiry, per the operator's 2026-10-20 request). The credential is stored in the site's WordPress option; no credential from another site was copied. This local setup does not deploy production or provide production access to tenants. A fresh application workload remains unverified; health reports the description adapter as `endpoint_unconfigured`.

## Deferred work

1. Provision and release an isolated `prod-auraface` API, worker, database role, database, volumes, and network through the maintained deployment flow. Verify capacity, image identity, model artifacts, and rollback before promotion.
2. Ensure Caddy joins the correct production AuraFace network and `prod-auraface-api:8000` resolves and accepts requests. Verify the active configuration as well as the file on disk.
3. Complete production tenant creation, site pairing, scoped key issuance, replacement, and revocation. Verify both the service workflow and the tenant-facing WordPress configuration. Keys must be issued against the selected production identity store, rather than a development or laptop fixture database.
4. Verify tenant isolation with at least two production test tenants, including recognition jobs, media, identities, clusters, and result retrieval. A key or tenant mismatch must not expose another tenant's records.
5. Preserve AuraFace's exact model/preprocessing/normalization/runtime contract and isolated 512D store. Generic InsightFace 512D and SFace 128D galleries remain separate; no automatic cross-model or cross-environment fallback.
6. Update onboarding documentation and any endpoint availability claims to distinguish configured, reachable, authenticated, functionally tested, and quality-qualified states. Add focused regression coverage for the deployment or onboarding defect actually corrected.

## Acceptance criteria

- The production hostname reaches the intended production AuraFace container and store, with public `/health` and `/ready` passing and the expected deployed image/source identity recorded.
- A newly onboarded production tenant can pair its own site, authenticate detailed health, submit an authorized recognition fixture, and retrieve its completed result through WordPress.
- Another tenant cannot read or mutate that tenant's jobs or recognition data; missing, invalid, revoked, and mismatched credentials return the intended authentication/authorization errors rather than a gateway failure.
- Actual vector typmods for media identities, cluster representatives, and centroids agree with the selected 512D model space. The smoke records genuine model execution and its provenance, rather than inferring inference from a health response.
- A deployment restart and rollback preserve the selected environment and tenant mappings. Existing development, generic production, and FIR endpoints retain their expected behavior.
- Production recognition-quality qualification is tracked separately and is not claimed from connectivity or a completed smoke job.

## Reopen and implementation boundaries

Promote this entry into a dated implementation task before offering production AuraFace to tenants or advertising its endpoint as available. Keep the local development workaround in place until a deliberate, verified client cutover. Recheck the live topology before implementation because the observations above are dated.

## References

- [Endpoint diagnosis and recovery plan](../../../benchmarks/reports/auraface-endpoint-diagnosis-plan-20261020.md)
- Evidence: `/Volumes/Butter/CodexEvidence/auraface-diagnosis-20261020/`
- Local switch evidence: `/Volumes/Butter/CodexEvidence/auraface-dev-switch-20261020/`
- Clerk provisioning and authenticated connection evidence: `/Volumes/Butter/CodexEvidence/auraface-clerk-key-20261020/provisioning-result.json`
- [AuraFace activation policy](../../adrs/ADR-016-auraface-512d-activation-refusal.md)
- [Tenant onboarding smoke test](../../runbooks/tenant-onboarding-smoke-test.md)
- [Key management](../../runbooks/key-management.md)
- Deployment: `scripts/deploy/recognition-service.sh` environment mappings and `is_prod_tier_env`
- Credentials: `apps/prototype-description-service/scripts/manage_api_keys.py`

This entry complements [generic OCI staging debt](oci-staging-environment-not-deployed.md); it specifically covers AuraFace production availability and tenant access.
