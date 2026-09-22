# Benchmarks

Tracked plans, manifests, reports, and tools for corpus measurement. Image
bytes stay local-only.

## Images

`benchmarks/images/` is the canonical gitignored image root. Layout:

- `mock_images/` — golden-37 scene fixtures
- `mock_entities/` — consented entity face crops
- `corpus646/originals/<bucket>/<file>` — source-space originals verified against `corpus-manifest-v3r` `sha256_source`
- `corpus646/provenance.json` (and `README.md` there) — provenance for the 646 originals

Corpus manifests carry `sha256_source` for those originals. The `images_root`
field in `corpus-manifest-v3r` points at a deleted worktree derived cache and
must not be relied on.

Re-hydrate mock fixtures from the Butter archive into this directory; see
`apps/prototype-description-service/scene/tests/seed/README.md`.
