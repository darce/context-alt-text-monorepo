# Benchmarks

Tracked plans, manifests, reports, and tools for corpus measurement. Image
pixels and private maps remain ignored and out of Git; the operator prefers
images not be uploaded to remote Git. Private image use and transfers follow
the actual existing task authorization, including already authorized remote
benchmark work and cleared image use. Private alias maps stay laptop-only.
Source-archive image basenames and private mappings do not belong in tracked text.

## Results

- [FIRBENCH-1 simulation acceptance, full v6 (2026-10-15)](reports/firbench-1-simulation-v6-20261015.md):
  numerical acceptance **FAILED** (6 gates PASS, 2 FAIL); frozen primary-checkout JSON remains authoritative. The independently pinned post-assembly synthetic AE-11 comprehension/browser component passes at `43522276` ([scope and proofs](reports/firbench-1-simulation-v6-20261015.md#91-independently-pinned-positive-stage-ae-11-component)); historical reader failures and real-data gates remain. [New-run instructions](reports/firbench-1-simulation-v6-20261015.md#10-verification) require an absent, separately named ignored target; never overwrite frozen evidence.

## Images

One authority locates the corpus: the tracked catalog
[`manifests/corpus-catalog-v1.json`](manifests/corpus-catalog-v1.json), read by
the shared resolver `scripts.eval_harness.corpus_catalog`. Refer to a corpus by
its logical ID and let the resolver find the root. Do not hand-build corpus paths
or use a laptop-specific absolute path.

| Logical ID | Entries | Hash field / space |
| --- | --- | --- |
| `corpus646-originals` | 646 v3r entries under `corpus646/originals/<bucket>/<file>` | `sha256_source` / `original` |

From the existing dev environment:

```bash
cd apps/prototype-description-service
python -m scripts.eval_harness.corpus_catalog show corpus646-originals
python -m scripts.eval_harness.corpus_catalog check corpus646-originals
```

- `show` prints the catalog metadata, the resolved root, and whether that root
  exists now. It verifies the manifest pin even when the root is absent, reads
  no image bytes, and does not establish a successful corpus check.
- `check` hashes each declared original and prints six counts (`entries`,
  `present`, `matched`, `missing`, `mismatched`, `unsafe_paths`), with no
  filenames, pixels, or mappings. Exit 0 means every entry is present and
  matched; 1 means incomplete, mismatched, or unsafe; 2 means a bad catalog,
  unknown ID, bad pin, or missing root.
- Both read the catalog and pinned manifest from the active source checkout,
  defaulting `--repo-root` from the installed module's source location, not the
  caller's working directory. `--repo-root` explicitly selects another checkout.
- An explicit `--corpus-root` overrides physical-root discovery and needs no Git
  discovery. It names the directory containing `originals/` and `provenance.json`,
  not `originals/` itself. Use it for bare, separate-git-dir, or relocated layouts,
  where the resolver does not guess a parent. For example, from the same service
  directory:

  ```bash
  python -m scripts.eval_harness.corpus_catalog show corpus646-originals --corpus-root /absolute/path/to/corpus646
  python -m scripts.eval_harness.corpus_catalog check corpus646-originals --corpus-root /absolute/path/to/corpus646
  ```

The catalog stores only the root layout and the manifest pin. It stores no
counts, availability, or `images_root`; those are read live.

### Where the bytes live

The default corpus root is the primary checkout's `benchmarks/images/corpus646/`,
ignored by the [`/benchmarks/**` rule](../.gitignore). In a normal `.git` layout,
the resolver discovers the primary checkout as the parent of Git's common
directory and appends the catalog's `root_relative`. Linked worktrees resolve
to that same physical root while reading their own catalog and manifest, so
feature worktrees need not contain images and must not copy them. Keep pixels
ignored there or outside the repository, never in tracked subdirectories;
private alias maps stay laptop-only.

Deriving a path does not show that images exist there or that their use is
authorized. The private source archive is recorded as present on the laptop. It
is known, not an active fallback: no command reads it, and its presence confers
neither eligibility nor consent.

| Path under `benchmarks/images/` | Contents / verification |
| --- | --- |
| `mock_images/` | golden-37 scene fixtures; legacy seed loader only |
| `mock_entities/` | entity face crops; legacy seed loader only |
| `corpus646/originals/<bucket>/<file>` | originals for 646 v3r entries; `<bucket>` is `personal` or `celebs`; logical ID `corpus646-originals`; verify `sha256_source` |
| `corpus646/provenance.json` | local provenance declaration, including the 3 absent entries (catalog `provenance_file`) |

The laptop observation recorded these locations as present, `corpus646/README.md`
as absent, and `provenance.json` as existing. Mock-fixture rehydration and the
legacy `GOLDEN_IMAGES_DIR` setting are in the
[seed README](../apps/prototype-description-service/scene/tests/seed/README.md#eval-harness-golden-seed-vlm-2a-corpus-vlm-2c-population).
The catalog never reads `GOLDEN_IMAGES_DIR`. FIRBENCH uses its existing private
input bindings; the catalog does not change them.

### Recorded status and hash provenance

The 2026-10-15 read-only laptop-primary observation recorded **643
of 646 originals matching `sha256_source`, 3 missing, 0 mismatched**: 643 files,
199,906,668 bytes. The 3 absent entries are declared in the local provenance
file, whose names stay out of Git. This is a dated observation, not a live fact
and not a fresh pixel check. Run `check corpus646-originals` for the current
result on the root it resolves; the result makes no claim about other locations.

The historical source manifest
[`corpus646-interleave-manifest-20260716.json`](manifests/corpus646-interleave-manifest-20260716.json)
is authoritative for lineage: its entry `sha256` equals
[v3r](manifests/corpus-manifest-v3r-20260814.json) `sha256_source` for all 646
entries, joined by `media_id`. For the originals protocol, **always use
v3r `sha256_source`** (`sha256_source_space = original`). V3r `sha256` describes
the downscaled space: 288 of 646 pairs are equal and 358 differ. Equality on
some entries does not change the protocol. The catalog pins the hash field
`sha256_source` in the `original` space. No command falls back to `sha256`,
and no step copies, downloads, or re-encodes pixels to make a hash match.

The 646 entries have 643 distinct source hashes; three hashes are each shared by
two entries. Count matches per entry, not per unique hash. The manifest `bytes`
total is 143,486,308 and is not established as measuring the same file version as
the recorded disk total. Its frozen `images_root` points to a deleted laptop
worktree's derived cache. It is historical only, the resolver ignores it, and the
manifest must not be rewritten.

### Read-only check

`check corpus646-originals` is the inspection method. It verifies that the pinned
v3r manifest bytes match the catalog's SHA-256, then streams each declared
original under the resolved root and compares `sha256_source`. A path that
escapes the images root, including through a symlink, is counted as unsafe and
not followed. The command reads and hashes bytes only. It decodes nothing and
writes nothing.

If the root is absent or unreadable, record that location and observation date;
entry-level counts are then unmeasured there. Remote checkout absence does not
establish corpus-wide absence. Run the check where the originals are available,
or use a private transfer already covered by the task authorization if remote
work needs pixels. A new use or transfer outside that authorization needs its
actual authorization resolved; there is no blanket stop or renewed-permission
requirement for cleared work.

### Remaining evidence limits

The [inventory §10](../docs/tasks/firdv/firbench-1/inventory.md#10-flags-for-downstream-lanes)
does not establish independently exhaustive human GT, observation or QC of
measurement production, or capture-occasion independence for this corpus.
`named_boxes` and `detected_boxes` do not establish independent exhaustive GT;
actual detector-independent exhaustive annotation and a separate detector-only
comparison are needed. The inspected v3r manifest has no `session_id` or
`synthetic_parent_id`; shared identities alone do not establish independent
occasions. These are limits of the inspected records, not global absence claims.


## Reproducer tools

Run from the checkout root; use `--help` for input details. JSON writers require
an explicit `--out` naming an absent destination, including no existing symlink.
Choose a new ignored run path for every invocation; never overwrite frozen
manifests or results. Input defaults resolve from the source checkout or corpus
resolver, independently of the caller's working directory.

```bash
python benchmarks/tools/build_corpus_manifest.py --corpus CORPUS --golden GOLDEN --detections DETECTIONS --images-root IMAGES --out benchmarks/results/new-corpus.json
python benchmarks/tools/build_golden_selection.py --corpus CORPUS --out benchmarks/results/new-golden.json
python benchmarks/tools/calibrate_slice_tags.py --detections DETECTIONS --golden GOLDEN --corpus CORPUS --out benchmarks/results/new-calibration.json
python benchmarks/tools/pose_features.py SOURCE --out benchmarks/results/new-pose.json
python benchmarks/tools/run_detection_pass.py --corpus CORPUS --images-root IMAGES --out benchmarks/results/new-detections.json
bash benchmarks/tools/openimages_occlusion_measure.sh /path/to/annotations
```

The Open Images tool accepts `OPENIMAGES_ANNOTATION_DIR` instead of the positional
directory and prints to stdout. It requires awk and Python with NumPy; its
historical [measurement record](reports/openimages-occlusion-MEASUREMENTS.md)
remains author-run and unreplicated. No measurement was rerun when adding source.
