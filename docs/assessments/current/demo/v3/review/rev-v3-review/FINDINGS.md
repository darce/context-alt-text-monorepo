## REV-V3_REVIEW-BR-01
severity: high
file: apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx
line: 58
canon_refs: FORM-09
summary: The new scope prop defaults to admin, but the production RecordedWalkthrough caller still omits scope when it renders GuidedDescriptionReview, so RecordedWalkthrough scope="public" reaches this default and renders the admin Preview button, preview gate, and before/after grid; the requested public editor and responsive Apply path are therefore unreachable.

## REV-V3_REVIEW-BR-02
severity: medium
file: apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx
line: 424
canon_refs: FORM-09
summary: The public click handler passes the visible text only to actions.onApplyForImage, whose existing production wiring still calls applyGuidedDraftForImage(next, imageKey) without the required third argument after an optional separate edit; the reducer consequently applies its preview-gated two-argument path and rejects the newly enabled unpreviewed draft, while the next line announces success, leaving Apply a no-op and status feedback false.

## REV-V3_REVIEW-BR-03
severity: high
file: apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedDescriptionReview.tsx
line: 544
canon_refs: none
summary: The public READY branch mounts guided-image-status-${key} here while the separate public non-READY branch mounts another copy at line 472; switching a card between BLOCKED or FIXTURE_MISSING and READY replaces the mutually exclusive subtree, destroying and recreating the status node instead of preserving one persistent initially empty region and its announcement continuity.
