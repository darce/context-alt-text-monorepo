# APP-1 billing namespace upgrade (drained writers)

> **SUPERSEDED — NOT AN IMPLEMENTATION OR OPERATING GUIDE.**
> Superseded on 2026-10-19 by [ADR-014: standard Stripe direct](../adrs/ADR-014-payment-processor-merchant-of-record-selection.md).
> Do not use this document to select a payment provider, provision credentials, calculate fees, or infer release readiness.

The obsolete provider recommendation, vendor-specific protocol, and operating commands have been removed. Standard Stripe payments on AltContext's own account is the selected design. AltContext is the seller and handles tax calculations, registration, collection and remittance; Stripe Managed Payments and merchant-of-record arrangements are excluded.

Use the current account/billing contract and the launch continuation for implementation work. Existing historical adapter tests do not qualify the selected Stripe integration. Real Stripe sandbox, signature, reconciliation and customer-journey evidence remain separate acceptance work.

Original source material is retained with SHA-256 custody outside the repository at `/Volumes/Butter/WorkBay/custody/stripe-docs-20261019/originals/`. It is historical evidence, not active guidance.
