## REV-V3_STEPPER-BR-01
severity: high
file: apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedPrototypeGuide.tsx
line: 106
canon_refs: NAV-09, NAV-13
summary: The new `scope` prop defaults to `'admin'`, but the existing public/admin `RecordedWalkthrough` caller does not pass its `scope` through to `GuidedPrototypeGuide`; public renders therefore take the admin branch with all four `GUIDE_STEPS`, admin labels, and four-step current numbering instead of the required two-stage public navigation. This breaks the pinned public stepper contract and makes its progress indicator announce the wrong flow.
