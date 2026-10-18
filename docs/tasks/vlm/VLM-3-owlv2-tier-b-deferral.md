# VLM-3 Slice 6 OWLv2 Tier B Deferral

Status: deferred
Date: 2026-07-08

Slice 6 is intentionally deferred until E20-BRAND-A lands ownership and schema for `ContextPack.brands`.

No production OWLv2 route or worker is enabled in VLM-3. Without the Scope A `ContextPack.brands` contract, an OWLv2 implementation would either write to an unowned field or invent a parallel brand path. Both would violate the VLM-3 plan boundary.

Resume criteria:

- E20-BRAND-A defines `ContextPack.brands` ownership, shape, and write authority.
- The description API contract documents how brand detections flow into captions.
- A new TDD slice can verify one OWLv2 detection instance flowing through the burst pool into `ContextPack.brands`.

Until then, the GPU burst pool work in Slices 1-5 remains reusable by OWLv2, but brand enrichment stays out of production code.
