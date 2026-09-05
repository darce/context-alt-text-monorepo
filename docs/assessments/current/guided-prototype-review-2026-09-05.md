# Guided prototype design review

Date: 2026-09-05. Scope: ASCII design and UX-map structure. No component build,
site change, guest account creation, GPU request or publication.

## Artifacts

- [Delivery decision, full ASCII screens and interaction contract](guided-prototype-design-2026-09-05.md)
- [Structural map](../../../apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.uxmap.json)
- [Generated ASCII and Mermaid bundle](../../../apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.md)

The full-width sketches are in the design document. The CLI bundle is the
deterministic structural rendering; its compact labels are intentionally shorter.
The map contains 13 screen/overlay/exit records and seven flows.

## Iteration evidence

1. Initial composition put a guide alongside the two plugin panes. Manual canon
   reasoning rejected the third column and tooltip/spotlight dependence. Revision
   2 puts a normal-flow guide above the existing workspace and includes a narrow
   layout, a text evidence path, explicit action outcomes and focus behavior.
2. The user's clarification made identity-informed prose the hero. Revision 2 now
   shows the visual draft, confirmed identity and context, named draft, and a text
   explanation of the change. This precedes edit/reject/apply and provenance detail.
3. First CLI critique returned two medium RLSE-04 findings: missing non-default
   reset-dialog and case-study exit states. Added reset loading/failure recovery
   and documented the browser-owned external exit failure boundary.
4. Second CLI critique returned `[]`. The actual RULE_PACK was inspected: eight
   enabled rules (RLSE-04, NAV-11, AGT-02, INT-07, HAI-01, HAI-16, INT-05, UI-06).
   This was not an empty or disabled engine. The pack checks declared structure;
   it does not test actual authorization, focus, contrast or model behavior.

## Reproduce

The available CLI is at
`/Users/daniel/Development/agentic-protocol-monorepo/.venv/bin/ux-map`.
Set `UXMAP_CLI` to that executable, or an equivalent installed `ux-map`.
Run from this repository root:

```sh
"$UXMAP_CLI" critique \
  --workspace-root "$PWD" \
  --maps-dir apps/prototype-wp-alt-context/docs/ux-maps \
  --map-ref guided-prototype --json

"$UXMAP_CLI" render \
  --workspace-root "$PWD" \
  --maps-dir apps/prototype-wp-alt-context/docs/ux-maps \
  --map-ref guided-prototype --format markdown \
  --out-dir apps/prototype-wp-alt-context/docs/ux-maps

"$UXMAP_CLI" render --check \
  apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.uxmap.json \
  apps/prototype-wp-alt-context/docs/ux-maps/guided-prototype.md \
  --workspace-root "$PWD" \
  --maps-dir apps/prototype-wp-alt-context/docs/ux-maps
```

## Evidence boundaries

Code discovery: current graph project
`Users-daniel-Development-context-alt-text-monorepo`; exact snippets and inbound
traces for identity merge/naming preview/correction; coverage checks for cited
implementation and benchmark paths. Semantic prior-work queries succeeded with
`gte-base-en-v1.5`, `embeddings_mode=verified`, no semantic degradation.

Network checks: anonymous homepage and media reads, WordPress login redirect,
and headless Chrome with the existing saved auth state. That state was expired;
authenticated admin visual inspection was not achieved. No settings/credentials
were printed. The existing admin code/maps supply the UI inventory.

Saved benchmark inspection counted 640 non-error descriptions in 646 items;
producer model and build were inspected. The ten-item fusion experiment is seeded,
and the named-preview harness seeds identities. These are separate evidence tiers,
not a single full-system accuracy result. The design explains their scope before
exposing any metric to a visitor.

Not run: component tests, axe, keyboard operation of the proposed UI, screen-reader
AT, unaided hiring-manager trial, or live GPU/WordPress end-to-end generation.
These require an implemented journey. Passing this map critique is **design
readiness evidence**, not accessibility conformance or production readiness.

## Next iteration criteria

Use the ASCII screens to answer these before component work:

- Is the generic-to-named change immediately understandable as the core feature?
- Can the reader distinguish sample metadata, human confirmation, generated or
  illustrative prose, and actual applied text?
- Does every action explain its scope and provide an obvious continuation?
- Can the same journey be followed using only text and keyboard-order reasoning?
- Does the existing plugin still look and behave like the product being evaluated?

When these hold, build the smallest saved-scenario slice in the actual plugin,
beginning with the description comparison and review/apply separation. Keep the
initial operator-guided delivery independent of the later invitation mechanism.
