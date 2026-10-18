lane dux-w2g-a
STATUS: IN_PROGRESS

---
## Orchestrator note (not lane output)

This lane expired at the 900s wall-clock cap mid-mutation and never produced a
verdict; the stub above is its checkpoint. It also left a mutant applied in its
sandbox, which was reverted before reuse.

Its lens (TEST VACUITY / TEST-15 against the RV-04 regex extraction and the new
RV-16 assertions) was executed directly on the same warm VM sandbox instead.
Result: baseline green, then 5/5 mutants killed - fabricated relative recency,
deleted [Open settings] (only when both mentions are removed; a single-site
deletion legitimately survives a section-wide check), mis-cited CTA gate,
invented summary case, and a component-side change bundling the CTA behind the
date. Reverted clean. See the commit that introduced RV-16.
