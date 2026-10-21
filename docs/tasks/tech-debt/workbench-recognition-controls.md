# Workbench facial recognition controls

**Status:** Deferred UI tech debt, registry item **#32**.
**Recorded:** 2026-10-20, at the operator's request.
**Priority:** Next Workbench UX pass.
**Owners:** WordPress frontend and recognition-policy owners; assign named owners when promoted.

## Problem

The Workbench does not make the site's facial recognition policy and its enable/disable actions apparent where recognition work occurs. On LocalWP `localhost:10033`, the development connection, tenant pairing, and sync passed while scanning was refused with HTTP 409, `recognition_disabled`: “People identification is turned off in Settings.” A working connection therefore looked ready while a separate policy prerequisite remained unmet.

The operator subsequently enabled recognition; Settings now returns `recognition_enabled: true`. That local configuration change resolves the gate for this site. The product still needs a visible, understandable way to make and revisit that choice within the Workbench.

## Intended behavior

Show **Facial recognition: On / Off** beside the relevant Workbench actions. Offer **Enable facial recognition** when off and **Disable facial recognition** when on, with equally accessible placement. Explain briefly that the choice applies to the whole site's media processing.

Use the existing administrator-controlled recognition policy as the single source of truth. Persist the choice across reloads and visits, and keep Workbench and Settings synchronized. Preserve affirmative opt-in and the off-by-default policy for a newly configured site. Once chosen, avoid repeatedly asking the same configuration question.

## Acceptance criteria

- The Workbench shows the effective policy state before a recognition action; when off, an administrator can enable it there without first encountering a failed scan.
- Enable and disable actions are equally discoverable, keyboard accessible, and clearly labelled. Users without the required capability see the state and an explanation of who can change it; server-side authorization remains enforced.
- A successful change persists through the existing settings API/policy, survives reload and revisiting the page, and appears consistently in both Settings and Workbench. No per-user preference or second policy store is introduced.
- Saving, success, and failure feedback appear beside the control. A failed save preserves the last confirmed state and offers a retry; the UI does not claim that an unsuccessful write took effect.
- Enabling changes the policy without automatically submitting media or starting the description GPU. Disabling clearly states its effect on future processing and does not imply that existing identity data was deleted or accepted jobs were cancelled.
- Recognition being enabled is distinguished from service connectivity and completed processing. Existing authentication, tenant isolation, and separate person-naming controls retain their contracts.
- Focused UI/API verification covers off-to-on, on-to-off, persistence, rejected writes, and insufficient capability. A new site's cold-start policy remains off.

## Design basis

Canon **v0.26.2**, verified against its release manifest during the investigation:

- **Biometric opt-in default** — [SECD-12](</Users/daniel/Development/heuristics-canon-v0.26.2/lexicons/security.md#secd-12>), *Face Recognition Technology (Compulsory Visibility)*, ch. 2: retain affirmative opt-in for face identity processing.
- **Make the safe path the easy path** — [SECD-08](</Users/daniel/Development/heuristics-canon-v0.26.2/lexicons/security.md#secd-08>), *Security Engineering*: make policy controls usable, with disablement as accessible as enablement.
- **Frequency elevates chrome** — [NAV-06](</Users/daniel/Development/heuristics-canon-v0.26.2/lexicons/interaction-ux.md#nav-06>), *Designing Interfaces, 3rd ed.* + *Microinteractions*, ch. 2: expose the relevant policy state and action where the activity occurs; a safety control remains visible even when infrequent.

## Implementation boundaries and references

Promote this entry to a dated implementation task before changing the UI. This entry records debt only. It does not change plugin behavior, the global default, production deployment, or description-service configuration.

- [Debt registry](current-debt.md)
- [Current endpoint investigation and setting design assessment](../../../benchmarks/reports/auraface-endpoint-diagnosis-plan-20261020.md)
- [Production AuraFace tenant access — separate debt #31](auraface-production-tenant-access.md)
- Existing policy: `apps/prototype-wp-alt-context/src/settings/class-recognition-policy.php`
- Existing settings and authorization: `apps/prototype-wp-alt-context/src/api/class-settings-controller.php`
- Workbench surface: `apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx`
- Enablement evidence: `/Volumes/Butter/CodexEvidence/auraface-clerk-key-20261020/recognition-enabled-20261020.json`
