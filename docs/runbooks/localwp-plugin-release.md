# LocalWP plugin release promotion

Use the published/prebuilt **ZIP and independently expected SHA256**, never a task
checkout, as the release input. `scripts/release/package-plugin.sh` in the plugin
is the sole builder: it already checks PHP/package versions, production Composer
contents and the JS source stamp. This installer neither builds nor changes a
version. `scripts/localwp/link-plugin.sh` remains a development helper.

## Operator invocation

From repository root (Linux, Python 3.9+, PHP CLI for syntax-only `php -n -l`):

```bash
python3 apps/prototype-wp-alt-context/scripts/localwp/install-release.py \
  --zip /stable/downloads/alt-context-0.0.38.zip \
  --sha256 95d6ec913f1d1ef7a5a91486d17c527405150e4813d389e9d4f071b436862f11 \
  --wp-path /absolute/wordpress/app/public \
  --store /stable/private/alt-context-releases \
  --dry-run
```

Remove `--dry-run` to promote. Add `--site-url https://your-site.example` to check
real served bytes. The URL is the WordPress root including any subdirectory;
assets are requested on that same origin, redirects refused, with a three-second
socket timeout per request and a 30-second budget checked between requests.
Readback compares SHA256 for **every retained graph file**, not just HTTP status.
The final request can finish after the budget by at most its socket timeout;
socket timeouts are not a strict deadline against a slow trickling server. Use a
trusted, responsive site URL. TLS verification uses Python defaults. No cookies,
credentials or secret configuration are accepted or written in receipts.

Use the same arguments with `--verify` to check the active view, validated PHP
header, manifest identity, all installed file digests and original custody ZIP.
A reinstall of the active digest does these checks without another view/backup.
`--dry-run` validates only the candidate, makes no site/store changes and reports
that scope; compatibility and retention checks run under the promotion lock.
All results, including errors, are JSON on stdout; errors exit nonzero. Save the
successful JSON as deployment evidence. The active view also contains
`.release-receipt.json`; it has paths and identities, so configure the web server
to deny dotfiles. Keep storage outside the web root and outside Git worktrees,
on persistent local storage, with trusted ownership and web-server read access.
Do not permit WordPress/plugin updater writes into these release views.

An existing active symlink is supported; its **actual installed manifest** seeds
compatibility, including both Vite manifest locations. Its target is preserved.
Managed upgrades also retain the receipt's entire compatibility graph without
requiring old ZIP arguments again.
An ordinary directory is refused: migrate it to a stable external directory and
symlink during an operator maintenance window first. Do not move a live directory
as an unrecorded part of promotion. A dangling active symlink is refused.

## First adoption with verified compatibility

The deployed 0.0.38 tree can contain the three operational 0.0.36 asset links
(`admin-BFoxEjkI.js`, `userFacingError-BlOiNgqA.js`,
`attachment-edit-DpE2a-VZ.js`). Default adoption refuses these links. Supply the
complete published 0.0.36 ZIP with its independently known SHA256; do not replace
the links with files as a workaround. Regular legacy assets outside the current
manifest require the same verified graph coverage.

For an already downloaded published hotfix, use the operator's trusted release
record for all expected digests (never derive the expected value from the same
download being checked):

```bash
: "${ACX_036_SHA256:?Set the independently known published 0.0.36 SHA256}"
: "${ACX_038_SHA256:?Set the independently known published 0.0.38 SHA256}"
: "${ACX_HOTFIX_ZIP:?Set the absolute path to the published hotfix ZIP}"
: "${ACX_HOTFIX_SHA256:?Set the independently known published hotfix SHA256}"
python3 apps/prototype-wp-alt-context/scripts/localwp/install-release.py \
  --zip "$ACX_HOTFIX_ZIP" --sha256 "$ACX_HOTFIX_SHA256" \
  --compat-zip /stable/downloads/alt-context-0.0.36.zip \
  --compat-sha256 "$ACX_036_SHA256" \
  --compat-zip /stable/downloads/alt-context-0.0.38.zip \
  --compat-sha256 "$ACX_038_SHA256" \
  --wp-path /absolute/wordpress/app/public \
  --store /stable/private/alt-context-releases \
  --site-url https://your-site.example
```

To adopt published 0.0.38 itself, use its ZIP/digest as the primary pair and keep
the 0.0.36 compatibility pair. There is no hardcoded 0.0.36 digest here.
`--compat-zip PATH` and `--compat-sha256 EXPECTED_DIGEST` are repeatable and paired
in order. Counts, digests, ZIP structure, complete graphs and path collisions
are checked before publication. Each compatibility input passes the same
canonical artifact validation as the primary ZIP. An unmanaged asset symlink
is accepted only when its path and exact served bytes match a verified graph;
the new view gets bytes from that ZIP. Unknown symlinks/static assets, missing
coverage and different bytes at a shared path refuse with the active tree
unchanged. No arbitrary symlink target becomes an artifact authority.

## What is published

ZIP digest, CRC reads, one `alt-context/` slug, unique safe paths, no traversal or
special files/symlinks, PHP entry/header, production autoload and manifest closure
are validated before promotion. ZIPs have a 512 MiB compressed/uncompressed limit
and 30,000 entries. All manifest nodes are traversed, including `imports`,
`dynamicImports`, `css` and `assets`; missing edges/files and escaping paths fail.
This trusts the canonical Vite manifest to describe the bundle: it is not a JS/CSS
parser and cannot discover undeclared runtime URLs. Production checks exclude
known development markers; PHP lint is not a dependency/security audit.

`artifacts/<sha256>/artifact.zip` preserves the exact supplied bytes read-only.
`views/<sha256>-<unique-id>/` contains the same extracted candidate files plus
copies of retained assets and the receipt. It never rewrites the custody ZIP or
published candidate assets. Copies make compatibility independent of old artifact
storage. The previous actual manifest, explicitly verified prior ZIP graphs and
previously recorded compatibility graph are accumulated through their full
closure. Prior ZIP digest provenance is recorded in the receipt, and supplied
compatibility ZIPs retain exact read-only custody in the same bounded store.
A shared path with different bytes is rejected, even if the filename resembles
a hash. No list of three filenames is maintained.
The receipt derives the version from the PHP header and records ZIP/manifest
SHA256, entry graph, complete file hashes, compatibility, previous target and its
artifact identity (or tree digest for an unmanaged prior install).

A per-site `flock` serializes promotions, including different store arguments.
A fully staged view is published using one `os.replace` of the plugin symlink.
Readers see a complete old or new tree. The site-specific store binding prevents
accidental cross-site reuse. Persistent files/directories are made read-only;
this is operational immutability, not protection against the storage owner.
A failed post-switch identity/readback check restores the prior link (or removes
the initial link); the failed view remains as evidence until safe orphan cleanup.
This handles reported process errors; there is no power-loss/fsync guarantee,
transaction journal or automatic recovery from SIGKILL during verification.

## Rollback and bounded retention

Supply the **previous install's ZIP and expected digest** with `--rollback`.
The recorded previous target must exist. Managed targets must match their receipt;
an original unmanaged target must match every extracted candidate byte. Rollback
publishes a fresh view of that artifact with the current compatibility graph, so
pages opened before rollback still have their modules. It records the rolled-from
target, allowing a later reversal. This does not roll back databases or backend
API behavior; caller gates must establish their compatibility separately.

There are at most **eight managed views and eight custody ZIPs per store**.
Retained graph bytes can grow to at most eight bounded artifacts plus the initial
unmanaged tree (also limited to 512 MiB on adoption). Limits stop
promotion; they never expire an open page's assets. Failed publication also
consumes capacity. The tool does not silently relax the limit.

`--reap` requires the active view to belong to the selected store's `views/`;
a store mismatch refuses before deletion. With the active ZIP/digest and matching
site/store arguments, it removes only validated orphan views not named by the
active link or **any** stored receipt's
previous pointer. A failed publication is normally such an orphan. Referenced
rollback views and all custody ZIPs are retained. Reaping takes the same site
lock and does not prune caches, external targets or source trees. All views carry
self-contained compatibility copies; no compatibility asset points into a reaped
view. Invalid/tampered receipts stop cleanup.

Routine successful history remains referenced. At the limit, keep the old store,
custody ZIPs, receipts (including dotfiles) and rollback targets intact. Inventory
every retained graph and its published ZIP/independently expected digest before
a maintenance handoff. Do not strip receipt metadata to evade validation. A
normal promotion into another site-bound store can preserve the old target and
support subsequent rollback using the new store; it does not authorize reaping
the old store while the active view belongs to the new one. There is no global
cross-store reference catalog or automatic successful-history retirement.

If the handoff tree is already metadata-free, its current manifest cannot prove
older graph coverage. A 0.0.38 tree still carrying 0.0.36 assets needs both
published ZIP graphs: use the hotfix adoption command above with the new store.
Every retained older graph needs coverage. Incomplete
coverage must refuse unchanged: recover the missing published ZIP and trusted
digest or restore the intact managed target/store, then retry. Copying assets
alone cannot establish provenance. Keep the old store until all site links,
rollback requirements and external consumers have been checked explicitly;
elapsed time alone does not make deletion safe. Supplied compatibility ZIPs
count toward the eight-artifact limit, so a new store is not an unbounded escape.

## Runtime gate remains an operator responsibility

The incident's stale PHP/old page requested `admin-BFoxEjkI.js?ver=0.0.36` after
0.0.38 replaced its directory. Entry-only repairs miss lazy modules. This view
keeps complete graphs reachable while the new entry becomes active.

Static readback proves served asset bytes; WP-CLI version output and PHP CLI lint
**do not prove PHP-FPM's loaded code or runtime cache identity**. Before calling a
release accepted, identify the exact LocalWP site's PHP-FPM service using the
operator's supported service authority. If needed perform a graceful reload of
that exact service, then load authenticated Overview freshly, inspect entry URL
and response bytes/CSS, and test an already-open page's lazy route. Record service,
scope, reload outcome and browser/network evidence. The installer has no shell
hooks, guessed PID kills, global cache prune or PHP cache-clearing endpoint.
Keep environment settings outside the artifact. Runtime endpoint validation is
a separate root join responsibility; static installer checks cannot prove it.

## Pinned decisions and evidence

Canon `v0.26.2` resolved to `1883d309b43665ba73b97da1b4aa4d2d1ee43f48`.
Stable IDs at their use:

- Custody ZIP: [RLSE-21 Promote the stored artifact](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#rlse-21), *Continuous Delivery*, ch. 5.
- Sole packager/pipeline: [RLSE-22 One route to production](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#rlse-22), *Continuous Delivery Pipelines*, ch. 2.
- External configuration: [RLSE-23 Promote the same candidate](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#rlse-23), *Continuous Delivery Pipelines*, ch. 9.
- Atomic staged view: [FLOW-01 Immutable inputs, complete replacement outputs](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#flow-01), *Designing Data-Intensive Applications*, ch. 10.
- Graphs and incoming rollback references: [GRPH-04 Compute the transitive closure deliberately](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/graph-theory.md#grph-04), *The Algorithm Design Manual*, ch. 18.
- Old/new pages coexist: [DATA-03 Schema evolution compat](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#data-03), *Designing Data-Intensive Applications*, ch. 4.
- Predicted RED: [TEST-06 Watch it fail once / predict the failure](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#test-06), *Modern Software Engineering*, ch. 8.
- Escaped regressions: [TEST-15 Prove the green can go red](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#test-15), *The Pragmatic Programmer*, ch. 9.
- Root joins both authors and retests every request: [TEST-33 Re-review every requested change](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#test-33), *Implementing Effective Code Reviews*, ch. 11.

Operator-supplied semantic priors (not re-created DB evidence): 17007 WBTRUST-0
requires served-build identity; 16293/16267 GTMSMOKE requires artifact release
context; 2930 ESMFIX-1 concerns module-loader correctness; 18305 identifies the
operator's latest-published request; 19177 separates the historical scan 400.
Frozen full QB priors 19183 (P1) and 19184 (P2), asset-gap prior 19178 and exact
old-asset/FPM repair prior 18307 govern this revision. These are operator-supplied
ONNX gte-base-en-v1.5 verified priors; this lane neither queries nor updates a DB.

### Dispatch2 validation and join

TESTDOCS keeps the installer frozen at native `35dd7ae877ff8a51d51b49d8d182d31be1720a24`
(tree `59d7ab5c6a9d6d168fdc00309d7b6e13f95d668a`, logical `97a08fda`).
The original 17 cases passed on VM with localhost sockets and native PHP before
adding the P1/P2 regressions (`17 passed in 30.88s`). The combined run returned
the predicted **18 failed, 18 passed in 51.31s**: 19 new cases give 18 expected
RED failures and one passing default-refusal guard, alongside the original 17
passes. Compatibility acceptance fails at `unrecognized arguments`; JSON refusal
checks reject that parser failure as integrity proof. Without compatibility
flags, uncovered regular assets and metadata-free adoption incorrectly succeed;
wrong-store reaping also succeeds and deletes A. Transcript:
`/tmp/AURA-RELEASE-TESTDOCS2/expected-red.txt` (exit 1, no environmental failures).
After strengthening refusal snapshots to include symlink-served bytes, the
targeted rerun gave `18 failed, 1 passed, 17 deselected in 17.39s`. The frozen
CLI independently accepted both synthetic complete ZIP fixtures in dry-run.
The tests cover full ZIP graph bytes, custody/provenance, all requested refusal
paths, metadata-free handoff coverage and cross-store reaping/rollback. CODE
and TESTDOCS are independent siblings: root must join both, run this exact test
file to GREEN, then run the independent Sol XHIGH gate. Planned RED here is not
implementation approval and does not require another TESTDOCS dispatch.

```bash
PYTHONDONTWRITEBYTECODE=1 timeout 180 \
  /home/gate/workbay-sandbox/.venv-lane-feature-auraface-plugin-release-20261018-923d6291/bin/python \
  -m pytest -q -p no:cacheprovider --tb=short scripts/test_plugin_release_install.py
```

### Historical baseline evidence

The original checkout was a history-stripped sandbox at
`65dfb605b04bbf449d6d2dc0d3753d739eeccd6e`; requested baseline
`16870bfc3ee5223a28696600e21d1afdad93c49f` is absent (`git` reports bad object).
No LocalWP site was deployed. No AnalyzeMediaService PHP/tests or SPA UI changed.

Native test command, one pytest process per run:

```text
pytest -q scripts/test_plugin_release_install.py
```

The initial native RED transcript is `/tmp/aura-release-b-red.txt`. Before the
installer existed, its decisive failure was Python's `can't open file` for
`apps/prototype-wp-alt-context/scripts/localwp/install-release.py` with
`[Errno 2] No such file or directory`. Native summary:

```text
8 failed, 1 passed in 1.39s
```

The passing original fixture demonstrated the naive swap lost both old module
paths; it now checks both actual HTTP 404 responses. The original installer tests
failed at the missing CLI before mutation. The final native GREEN transcript is
`/tmp/aura-release-b-green.txt`; final result is recorded below.

<details>
<summary>Native RED transcript (before installer existed; trailing whitespace trimmed)</summary>

```text
.FFFFFFFF                                                                [100%]
=================================== FAILURES ===================================
_________________ test_graph_coexistence_idempotence_rollback __________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_graph_coexistence_idempot0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_graph_coexistence_idempot0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_graph_coexistence_idempot0/releases'))

    def test_graph_coexistence_idempotence_rollback(tmp_path, site):
        a, b = artifact(tmp_path, '1'), artifact(tmp_path, '2')
>       first = run(site, a)
                ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:65:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_graph_coexistence_idempot0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_graph_coexistence_idempot0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_graph_coexistence_idempot0/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
_____________________ test_bad_candidate_unchanged[digest] _____________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_d0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_d0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_d0/releases'))
bad = 'digest'

    @pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug'])
    def test_bad_candidate_unchanged(tmp_path, site, bad):
>       a = artifact(tmp_path, '1'); run(site, a)
                                     ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:88:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_d0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_d0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_d0/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
____________________ test_bad_candidate_unchanged[missing] _____________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_m0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_m0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_m0/releases'))
bad = 'missing'

    @pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug'])
    def test_bad_candidate_unchanged(tmp_path, site, bad):
>       a = artifact(tmp_path, '1'); run(site, a)
                                     ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:88:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_m0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_m0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_m0/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
___________________ test_bad_candidate_unchanged[traversal] ____________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_t0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_t0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_t0/releases'))
bad = 'traversal'

    @pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug'])
    def test_bad_candidate_unchanged(tmp_path, site, bad):
>       a = artifact(tmp_path, '1'); run(site, a)
                                     ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:88:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_t0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_t0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_t0/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
___________________ test_bad_candidate_unchanged[collision] ____________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_c0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_c0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_c0/releases'))
bad = 'collision'

    @pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug'])
    def test_bad_candidate_unchanged(tmp_path, site, bad):
>       a = artifact(tmp_path, '1'); run(site, a)
                                     ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:88:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_c0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_c0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_c0/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
____________________ test_bad_candidate_unchanged[symlink] _____________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s0/releases'))
bad = 'symlink'

    @pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug'])
    def test_bad_candidate_unchanged(tmp_path, site, bad):
>       a = artifact(tmp_path, '1'); run(site, a)
                                     ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:88:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s0/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
______________________ test_bad_candidate_unchanged[slug] ______________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s1')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s1/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s1/releases'))
bad = 'slug'

    @pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug'])
    def test_bad_candidate_unchanged(tmp_path, site, bad):
>       a = artifact(tmp_path, '1'); run(site, a)
                                     ^^^^^^^^^^^^

scripts/test_plugin_release_install.py:88:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s1/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s1/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_bad_candidate_unchanged_s1/1.zip')
ok = True, args = ()

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
_______________________ test_dry_run_and_failed_readback _______________________

tmp_path = PosixPath('/tmp/pytest-of-gate/pytest-960/test_dry_run_and_failed_readba0')
site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_dry_run_and_failed_readba0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_dry_run_and_failed_readba0/releases'))

    def test_dry_run_and_failed_readback(tmp_path, site):
>       a = artifact(tmp_path, '1'); run(site, a, '--dry-run')
                                     ^^^^^^^^^^^^^^^^^^^^^^^^^

scripts/test_plugin_release_install.py:105:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

site = (PosixPath('/tmp/pytest-of-gate/pytest-960/test_dry_run_and_failed_readba0/wp'), PosixPath('/tmp/pytest-of-gate/pytest-960/test_dry_run_and_failed_readba0/releases'))
archive = PosixPath('/tmp/pytest-of-gate/pytest-960/test_dry_run_and_failed_readba0/1.zip')
ok = True, args = ('--dry-run',)

    def run(site, archive, *args, ok=True):
        wp, store = site
        result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
>       assert (result.returncode == 0) == ok, result.stdout+result.stderr
E       AssertionError: python3: can't open file '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory
E
E       assert (2 == 0) == True
E        +  where 2 = CompletedProcess(args=['python3', '/home/gate/workbay-sandbox/feature-auraface-plugin-release-20261018-923d6291/apps/p...018-923d6291/apps/prototype-wp-alt-context/scripts/localwp/install-release.py': [Errno 2] No such file or directory\n").returncode

scripts/test_plugin_release_install.py:44: AssertionError
=========================== short test summary info ============================
FAILED scripts/test_plugin_release_install.py::test_graph_coexistence_idempotence_rollback
FAILED scripts/test_plugin_release_install.py::test_bad_candidate_unchanged[digest]
FAILED scripts/test_plugin_release_install.py::test_bad_candidate_unchanged[missing]
FAILED scripts/test_plugin_release_install.py::test_bad_candidate_unchanged[traversal]
FAILED scripts/test_plugin_release_install.py::test_bad_candidate_unchanged[collision]
FAILED scripts/test_plugin_release_install.py::test_bad_candidate_unchanged[symlink]
FAILED scripts/test_plugin_release_install.py::test_bad_candidate_unchanged[slug]
FAILED scripts/test_plugin_release_install.py::test_dry_run_and_failed_readback
8 failed, 1 passed in 1.39s
```

</details>

<details>
<summary>Native final GREEN transcript</summary>

```text
.................                                                        [100%]
17 passed in 35.20s
```

</details>
