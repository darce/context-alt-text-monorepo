# R3 verdict: mutations survive

Independent falsification audit of the TEST-15 drift-guard claim in
`scripts/deploy/tests/test-smoke-gate.sh` lines 88–91. Auditor: lane
`demolive-r3` on `feature/demolive-r3`. Every mutation below was applied,
observed, then reverted before the next experiment. Working tree had no
mutations at commit time.

## Experiment 1 — claimed drift proof

Command: `bash scripts/deploy/tests/test-smoke-gate.sh; echo "exit=$?"`

Baseline exit: `0`
Assertion count: `55` `ok` lines, then `all assertions passed`

Mutation applied:

```diff
diff --git a/apps/prototype-description-service/scene/application/seeded_adapter.py b/apps/prototype-description-service/scene/application/seeded_adapter.py
--- a/apps/prototype-description-service/scene/application/seeded_adapter.py
+++ b/apps/prototype-description-service/scene/application/seeded_adapter.py
@@ -30,6 +30,7 @@ _FIXTURE_POOL: tuple[dict[str, Any], ...] = (
     {"caption": "Two people seated indoors in conversation.", "objects": ("person", "chair"), "ocr_text": None},
     {"caption": "A building exterior seen from the street.", "objects": ("building", "sky"), "ocr_text": None},
     {"caption": "A pet animal resting on a soft surface.", "objects": ("animal",), "ocr_text": None},
+    {"caption": "R3-SENTINEL a caption that is not in the shell gate.", "objects": ("sentinel",), "ocr_text": None},
 )
```

Sentinel string confirmed absent from `scripts/deploy/lib/smoke-gate.sh`
before the run.

Post-mutation exit: `1`
Failing line (verbatim):

```
FAIL drift: pool caption classified FAIL (R3-SENTINEL a caption that is not in the shell gate.): expected FAIL, got PASS
```

Also: `1 assertion(s) failed`

Revert: `git checkout -- apps/prototype-description-service/scene/application/seeded_adapter.py`
Reverted and re-green: yes (`exit=0`, `all assertions passed`; `git status --short` empty for that file)

Claim in the source comment is: REPRODUCED WITH DIFFERENCES: independent
sentinel `R3-SENTINEL a caption that is not in the shell gate.` instead of
the comment's `A drift sentinel caption that is not in the shell gate.`;
same FAIL line shape, same `expected FAIL, got PASS`, same exit `1`. The
comment is not fabricated.

## Experiment 2 — opposite direction (delete one shell case)

Command: `bash scripts/deploy/tests/test-smoke-gate.sh; echo "exit=$?"`

Baseline (after exp 1 revert): exit `0`

Mutation applied: deleted the pet-animal `case` block from
`classify_alt_provenance` in `scripts/deploy/lib/smoke-gate.sh`:

```diff
diff --git a/scripts/deploy/lib/smoke-gate.sh b/scripts/deploy/lib/smoke-gate.sh
--- a/scripts/deploy/lib/smoke-gate.sh
+++ b/scripts/deploy/lib/smoke-gate.sh
@@ -124,8 +124,5 @@ classify_alt_provenance() {
     case "$sample" in
         *"A building exterior seen from the street."*) echo FAIL; return ;;
     esac
-    case "$sample" in
-        *"A pet animal resting on a soft surface."*) echo FAIL; return ;;
-    esac
     echo PASS
 }
```

Post-mutation exit: `1`
Failing lines (verbatim):

```
FAIL alt provenance fixture: pet animal: expected FAIL, got PASS
FAIL drift: pool caption classified FAIL (A pet animal resting on a soft surface.): expected FAIL, got PASS
```

Also: `2 assertion(s) failed`

The drift loop named the deleted-case caption. The hardcoded fixture
assertion also went red (expected: that caption is tested twice). Guard
is coupled to the shell classifier, not merely to a static list in the
test file.

Revert: `git checkout -- scripts/deploy/lib/smoke-gate.sh`
Reverted and re-green: yes (`exit=0`; `git status --short` empty)

## Experiment 3 — formatting brittleness and zero-extraction

### 3a. Current-tree extraction vs pool size

Command (same pipeline as `test-smoke-gate.sh` lines 106–107):

```
grep '"caption":' apps/prototype-description-service/scene/application/seeded_adapter.py | sed 's/.*"caption": "\([^"]*\)".*/\1/'
```

Extracted captions: `8`
True `_FIXTURE_POOL` entries (Python AST `ast.literal_eval`): `8`

The already-black-formatted multi-line dict (scenic landscape, lines
23–27) still has `"caption": "value"` on one line, so grep extracts it.
On the current tree the guard is not partially blind.

### 3b. Split `"caption":` from the string (valid Python)

Mutation applied:

```diff
     {
-        "caption": "A scenic landscape with mountains under a clear sky.",
+        "caption":
+        "A scenic landscape with mountains under a clear sky.",
         "objects": ("mountain", "sky"),
         "ocr_text": None,
     },
```

Extracted count stayed `8`, but one extracted value was the garbage line
`        "caption":` (sed capture failed). Python pool still has 8 real
captions; scenic landscape is no longer in the extracted set.

Command: `bash scripts/deploy/tests/test-smoke-gate.sh; echo "exit=$?"`
Post-mutation exit: `1`
Failing line (verbatim):

```
FAIL drift: pool caption classified FAIL (        "caption":): expected FAIL, got PASS
```

Not a silent miss: fail-closed on unparseable extraction. Reverted;
re-green `exit=0`.

### 3c. Single-quoted key `'caption':` (surviving mutant)

Mutation applied:

```diff
-        "caption": "A scenic landscape with mountains under a clear sky.",
+        'caption': "A scenic landscape with mountains under a clear sky.",
```

Extracted count: `7` (scenic landscape dropped)
True pool length: `8`

Command: `bash scripts/deploy/tests/test-smoke-gate.sh; echo "exit=$?"`
Post-mutation exit: `0`
Failing line: none. Suite printed `all assertions passed`.

This is a coverage hole. Zero-extraction is the only cardinality check;
a partial miss does not fail. Reverted; re-green `exit=0`.

### 3d. Zero-extraction path

Mutation applied: pointed `adapter_file` in
`scripts/deploy/tests/test-smoke-gate.sh` at `/tmp/r3-no-captions.py`
containing `_FIXTURE_POOL = ({"objects": ("x",)},)` (no `"caption":`).
`grep '"caption":'` on that file exited `1`.

Command: `bash scripts/deploy/tests/test-smoke-gate.sh; echo "exit=$?"`
Post-mutation exit: `1`
Failing line (verbatim):

```
FAIL fixture-pool extraction produced zero captions from /tmp/r3-no-captions.py
```

Does not pass vacuously. Revert: `git checkout -- scripts/deploy/tests/test-smoke-gate.sh`;
removed `/tmp/r3-no-captions.py`. Re-green `exit=0`.

## Experiment 4 — describe-gate suite

Command: `bash infra/oci/demo/tests/test-describe-gate.sh; echo "exit=$?"`

Baseline exit: `0`
Assertion count: `38` `ok` lines, then `all assertions passed`

### 4a. Exact match → substring match

Mutation applied:

```diff
 is_trusted_describe_profile() {
     local profile="$1"
-    local candidate
     [ -n "$profile" ] || return 1
-    for candidate in $ACX_TRUSTED_DESCRIBE_PROFILES; do
-        [ "$candidate" = "$profile" ] && return 0
-    done
+    case "$ACX_TRUSTED_DESCRIBE_PROFILES" in
+        *"$profile"*) return 0 ;;
+    esac
     return 1
 }
```

Post-mutation exit: `1`
Failing lines (verbatim):

```
FAIL is_trusted florence (not prefix): expected 1, got 0
FAIL is_trusted small (not suffix): expected 1, got 0
```

Also: `2 assertion(s) failed`

Those two assertions are not decorative. Note:
`assert_predicate_matches_classifier` for `florence`/`small` stayed green
because it derives expected from the mutated predicate (agreement still
holds; both now treat the substring as trusted). The dedicated
`is_trusted` exit-code assertions are what catch this.

Revert: `git checkout -- infra/oci/demo/lib/describe-gate.sh`
Reverted and re-green: yes (`exit=0`)

### 4b. Unknown profile BLOCK → RUN

Mutation applied:

```diff
     if ! is_trusted_describe_profile "$profile"; then
-        echo BLOCK
+        echo RUN
         return
     fi
```

Post-mutation exit: `1`
Failing lines (verbatim, first and the unknown-profile pair):

```
FAIL seeded 100 0 (live situation): expected BLOCK, got RUN
FAIL empty profile 100 0: expected BLOCK, got RUN
FAIL unknown_profile 100 0: expected BLOCK, got RUN
FAIL hosted_gpt4o 100 0 (stub): expected BLOCK, got RUN
FAIL gpu_phi4 100 0 (stub): expected BLOCK, got RUN
FAIL florence_large 100 0 (stub): expected BLOCK, got RUN
FAIL SEEDED 100 0 (case hole): expected BLOCK, got RUN
FAIL seeded empty empty (profile first): expected BLOCK, got RUN
FAIL predicate/classifier agree 'seeded' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree '' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'SEEDED' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'florence' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'small' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'unknown_profile' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'hosted_gpt4o' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'gpu_phi4' 100 0: expected BLOCK, got RUN
FAIL predicate/classifier agree 'florence_large' 100 0: expected BLOCK, got RUN
```

Also: `17 assertion(s) failed`

Unknown-profile BLOCK is not decorative. Reverted and re-green: yes
(`exit=0`)

## Findings

### R3-01 | severity: medium | file: scripts/deploy/tests/test-smoke-gate.sh:106

Evidence: the drift loop extracts captions with
`grep '"caption":' | sed 's/.*"caption": "\([^"]*\)".*/\1/'`. Changing one
`_FIXTURE_POOL` key from `"caption"` to `'caption'` dropped extraction
from 8 to 7. Command `bash scripts/deploy/tests/test-smoke-gate.sh`
exited `0` with `all assertions passed`. The scenic-landscape caption
was no longer asserted by the drift loop.

Failure scenario: a fixture is added or reformatted with a single-quoted
key (valid Python; black usually rewrites it, but the guard does not run
black). The hardcoded per-caption assertions in the same file still
cover today's eight strings, so a *new* ninth caption with `'caption':`
would be the live hole — Experiment 1 only catches a ninth caption if
grep sees `"caption":`.

Canon: TEST-15 / CLM-04 — a green suite is not evidence that every pool
caption is classified. A partially-blind guard reads as full coverage.

Suggested fix: parse `_FIXTURE_POOL` with Python `ast` (or fail unless
extracted count equals `len(_FIXTURE_POOL)`). Do not treat `extracted -gt 0`
as complete coverage.

## Surviving mutants

- `'caption':` (single-quoted dict key) on one `_FIXTURE_POOL` entry in
  `apps/prototype-description-service/scene/application/seeded_adapter.py`.
  Extraction 7/8. Suite stayed green (`exit=0`). See R3-01.

Killed mutants (not holes): 9th pool caption (exp 1); deleted shell
`case` (exp 2); split-line `"caption":` / value (exp 3b, fail-closed);
zero-extraction (exp 3d, fail-closed); substring `is_trusted` (exp 4a);
unknown-profile `BLOCK`→`RUN` (exp 4b).

## Tree state

After every revert, then after committing this file on `feature/demolive-r3`:

```
$ git status --short
(empty)
```

`main` does not exist in this sandbox (history-stripped; base branch is
`master`). Command as specified:

```
$ git diff --stat main...HEAD
fatal: ambiguous argument 'main...HEAD': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
```

```
$ git diff --stat master...HEAD
 docs/reviews/DEMOLIVE-9/demolive-r3-verdict.md | 323 +++++++++++++++++++++++++
 1 file changed, 323 insertions(+)
```

The only file added versus `master` (and versus sibling lanes) is this
verdict file. No mutation remains in the tree.
