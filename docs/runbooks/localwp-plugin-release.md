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
An ordinary directory is refused: migrate it to a stable external directory and
symlink during an operator maintenance window first. Do not move a live directory
as an unrecorded part of promotion. A dangling active symlink is refused.

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
storage. The previous actual manifest and previously recorded compatibility graph
are accumulated automatically. A shared path with different bytes is rejected,
even if the filename resembles a hash. No list of three filenames is maintained.
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

`--reap`, with the active ZIP/digest and normal site/store arguments, removes only
validated orphan views not named by the active link or **any** stored receipt's
previous pointer. A failed publication is normally such an orphan. Referenced
rollback views and all custody ZIPs are retained. Reaping takes the same site
lock and does not prune caches, external targets or source trees. All views carry
self-contained compatibility copies; no compatibility asset points into a reaped
view. Invalid/tampered receipts stop cleanup.

Routine successful history remains referenced. At the limit, schedule explicit
operator retirement: quiesce the site, decide the rollback/audit horizon, keep an
offline archive if needed, and move a verified self-contained active tree to a
new stable external directory **without installer metadata**. Point the site at
that tree, verify it and close the old history only after checking no site link,
rollback requirement or external consumer references the old store. A fresh store
can then adopt that actual manifest. Preserve the complete compatibility files
while open-page support is required. There is no automatic successful-history
retirement or assertion that an arbitrary number of days makes deletion safe.

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
Keep environment settings outside the artifact. The published 0.0.38 PHP service
was identical to main: changing this release pipeline does not fix the independent
scan/backend 400 issue and has no source-A implementation dependency.

## Pinned decisions and evidence

Canon `v0.26.2` resolved to `1883d309b43665ba73b97da1b4aa4d2d1ee43f48`.
Stable IDs at their use:

- Exact custody ZIP and sole existing packager: [RLSE-21](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#rlse-21), [RLSE-22](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#rlse-22).
- Same candidate with external configuration: [RLSE-23](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#rlse-23).
- Complete staged view and atomic publication: [FLOW-01](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#flow-01).
- Deliberate manifest transitive closure: [GRPH-04](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/graph-theory.md#grph-04).
- Old/new page coexistence applies the rolling compatibility principle: [DATA-03](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#data-03).
- Missing-implementation RED before implementation: [TEST-06](https://github.com/darce/heuristics-canon/blob/1883d309b43665ba73b97da1b4aa4d2d1ee43f48/lexicons/engineering.md#test-06).

Operator-supplied semantic priors (not re-created DB evidence): 17007 WBTRUST-0
requires served-build identity; 16293/16267 GTMSMOKE requires artifact release
context; 2930 ESMFIX-1 concerns module-loader correctness; 18305 identifies the
operator's latest-published request; 19177 separates the scan 400. No primary
knowledge/decision MCP or configured remote DB is available in this session.
These local source decisions are handed back for the root's primary MCP record;
no remote database is claimed as primary or updated here.

The checkout is a history-stripped sandbox at
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
