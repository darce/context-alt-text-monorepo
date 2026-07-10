# Refactor skill bodies — moved to canonical home

The repo-tuned REFACTOR skills drafted from the distilled books now live in the
canonical cross-harness skill surface (single source of truth, composed into
every harness plugin tree):

- `workbay-overrides/workbay-system/skills/refactor-wp-alt-context/SKILL.md`
- `workbay-overrides/workbay-system/skills/refactor-description-service/SKILL.md`

Registered as `mode: add` components in
`workbay-overrides/workbay-system/overrides.yaml`. `make plugins-build`
composes them byte-identical into
`.workbay/generated/plugins/workbay-system/effective/{claude,codex}/skills/`
(Claude loads via `.claude-plugin/marketplace.json`, Codex via
`.agents/plugins/marketplace.json`). `make plugins-check` guards drift.

Source material: [`../distilled/`](../distilled/) (8 abridged books).
