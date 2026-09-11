## REV-V3_PHOTO-BR-01
severity: medium
file: apps/prototype-wp-alt-context/js/admin/pages/guided/GuidedSamplePhoto.tsx
line: 74
canon_refs: sr-007
summary: The new caption branches and baseline-span gate compare the scope domain value directly with scattered 'public'/'admin' string literals (lines 74, 101, and 216) instead of using a shared as-const scope vocabulary. This violates sr-007 and duplicates the public/admin discriminator across three independent literals, so a future scope rename or addition can drift between provider headings and baseline visibility.
