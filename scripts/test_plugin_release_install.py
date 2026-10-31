"""Synthetic Linux promotion tests; no WordPress, database or build required."""
import contextlib
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import urllib.request
import urllib.error
import zipfile

import pytest

CLI = Path(__file__).resolve().parents[1] / 'apps/prototype-wp-alt-context/scripts/localwp/install-release.py'
DIST = 'public/assets/dist/'


def artifact(tmp, version, **changes):
    files = {'alt-context.php': '<?php\n/**\n * Plugin Name: Alt Context\n * Version: '+version+'\n */\n',
             'vendor/autoload.php': '<?php\n',
             DIST+'.vite/manifest.json': json.dumps({'admin': {'file': f'assets/admin-{version}.js', 'isEntry': True, 'dynamicImports': ['lazy'], 'css': [f'assets/style-{version}.css'], 'imports': ['shared']}, 'shared': {'file': 'assets/shared-stable.js', 'imports': ['deep']}, 'deep': {'file': 'assets/deep-stable.js', 'css': ['assets/deep-stable.css']}, 'lazy': {'file': f'assets/lazy-{version}.js', 'assets': [f'assets/image-{version}.svg']}})}
    for name in [f'admin-{version}.js', f'lazy-{version}.js', f'style-{version}.css', f'image-{version}.svg']:
        files[DIST+'assets/'+name] = name
    for name in ('shared-stable.js', 'deep-stable.js', 'deep-stable.css'):
        files[DIST+'assets/'+name] = name
    files.update(changes)
    path = tmp / (version+'.zip')
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            if data is not None:
                z.writestr('alt-context/'+name, data)
    return path


@pytest.fixture
def site(tmp_path):
    wp = tmp_path/'wp'
    (wp/'wp-content/plugins').mkdir(parents=True)
    (wp/'wp-load.php').touch()
    return wp, tmp_path/'releases'


def run(site, archive, *args, ok=True):
    wp, store = site
    result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True, timeout=25)
    assert (result.returncode == 0) == ok, result.stdout+result.stderr
    return json.loads(result.stdout) if ok else result


def test_naive_swap_loses_entry_and_lazy(tmp_path, site):
    wp, _ = site
    old, new = tmp_path/'old', tmp_path/'new'
    old.mkdir(); new.mkdir()
    for n in ('entry.js', 'lazy.js'):
        (old/n).write_text(n)
    active = wp/'wp-content/plugins/alt-context'
    active.symlink_to(old)
    replacement = active.with_name('replacement')
    replacement.symlink_to(new)
    os.replace(replacement, active)
    handler = lambda *args, **kw: http.server.SimpleHTTPRequestHandler(*args, directory=str(wp), **kw)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        for name in ('entry.js', 'lazy.js'):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/wp-content/plugins/alt-context/'+name)
            assert error.value.code == 404
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_graph_coexistence_idempotence_rollback(tmp_path, site):
    a, b = artifact(tmp_path, '1'), artifact(tmp_path, '2')
    first = run(site, a)
    second = run(site, b)
    active = site[0]/'wp-content/plugins/alt-context'
    handler = lambda *args, **kw: http.server.SimpleHTTPRequestHandler(*args, directory=str(site[0]), **kw)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        receipt = run(site, b, '--verify', '--site-url', url)
        assert receipt['http_verified']
        for v in ('1', '2'):
            for name in (f'admin-{v}.js', f'lazy-{v}.js', f'style-{v}.css', f'image-{v}.svg'):
                assert urllib.request.urlopen(url+'/wp-content/plugins/alt-context/'+DIST+'assets/'+name).read() == name.encode()
    finally:
        server.shutdown(); server.server_close(); thread.join()
    assert run(site, b)['view'] == second['view']
    assert len(list((site[1]/'views').iterdir())) == 2
    run(site, a, '--rollback')
    assert active.resolve() != Path(first['view'])
    assert (active/(DIST+'assets/admin-2.js')).read_bytes() == b'admin-2.js'
    assert json.loads((active/'.release-receipt.json').read_text())['artifact_sha256'] == first['artifact_sha256']


@pytest.mark.parametrize('bad', ['digest', 'missing', 'traversal', 'collision', 'symlink', 'slug', 'php', 'autoload', 'corrupt', 'deep'])
def test_bad_candidate_unchanged(tmp_path, site, bad):
    a = artifact(tmp_path, '1'); run(site, a)
    active = site[0]/'wp-content/plugins/alt-context'
    before = active.readlink()
    changes = {}
    if bad == 'deep': changes[DIST+'assets/deep-stable.css'] = None
    if bad == 'php': changes['alt-context.php'] = '<?php invalid !!!'
    if bad == 'autoload': changes['vendor/autoload.php'] = None
    if bad == 'missing': changes[DIST+'assets/lazy-2.js'] = None
    if bad == 'collision': changes[DIST+'assets/admin-1.js'] = 'different'
    b = artifact(tmp_path, '2', **changes)
    if bad in ('traversal', 'slug', 'symlink'):
        with zipfile.ZipFile(b, 'a') as z:
            info = zipfile.ZipInfo({'traversal': 'alt-context/../escape', 'slug': 'other/file', 'symlink': 'alt-context/link'}[bad])
            if bad == 'symlink': info.external_attr = 0o120777 << 16
            z.writestr(info, 'bad')
    if bad == 'corrupt':
        b.write_bytes(b.read_bytes()[:-20])
    run(site, b, *(['--sha256', '0'*64] if bad == 'digest' else []), ok=False)
    assert active.readlink() == before


def test_dry_run_and_failed_readback(tmp_path, site):
    a = artifact(tmp_path, '1'); run(site, a, '--dry-run')
    assert not (site[0]/'wp-content/plugins/alt-context').exists()
    run(site, a)
    active = site[0]/'wp-content/plugins/alt-context'; before = active.readlink()
    run(site, artifact(tmp_path, '2'), '--site-url', 'http://127.0.0.1:1', ok=False)
    assert active.readlink() == before
    assert len(run(site, a, '--reap')['reaped_views']) == 1
    assert run(site, a, '--reap')['reaped_views'] == []


def test_existing_install_and_bounded_retention(tmp_path, site):
    a = artifact(tmp_path, '0')
    old = tmp_path/'external'; old.mkdir()
    with zipfile.ZipFile(a) as z:
        z.extractall(old)
    active = site[0]/'wp-content/plugins/alt-context'
    active.symlink_to(old/'alt-context')
    for number in range(1, 9):
        run(site, artifact(tmp_path, str(number)))
    before = active.readlink()
    assert (active/(DIST+'assets/lazy-0.js')).is_file()
    run(site, artifact(tmp_path, '9'), ok=False)
    assert active.readlink() == before
    assert (old/'alt-context/alt-context.php').is_file()


def test_view_tampering_detected(tmp_path, site):
    a = artifact(tmp_path, '1'); run(site, a)
    asset = site[0]/'wp-content/plugins/alt-context'/DIST/'assets/lazy-1.js'
    asset.chmod(0o644); asset.write_text('tampered')
    run(site, a, '--verify', ok=False)


def test_concurrent_idempotent_install(tmp_path, site):
    from concurrent.futures import ThreadPoolExecutor
    archive = artifact(tmp_path, '1')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, site, archive) for _ in range(2)]
        results = [f.result() for f in futures]
    assert results[0]['view'] == results[1]['view']
    assert len(list((site[1]/'views').iterdir())) == 1


def test_rollback_to_original_external_install(tmp_path, site):
    old_zip = artifact(tmp_path, '1')
    external = tmp_path/'original'; external.mkdir()
    with zipfile.ZipFile(old_zip) as z:
        z.extractall(external)
    active = site[0]/'wp-content/plugins/alt-context'
    active.symlink_to(external/'alt-context')
    run(site, artifact(tmp_path, '2'))
    result = run(site, old_zip, '--rollback')
    assert result['rolled_back'] and result['version'] == '1'
    assert (active/(DIST+'assets/lazy-2.js')).is_file()


# QB P1/P2: these are published-path examples in a synthetic complete graph,
# not an implementation allowlist. CSS, image and deep imports must survive too.
LEGACY_LINKS = ('admin-BFoxEjkI.js', 'userFacingError-BlOiNgqA.js',
                'attachment-edit-DpE2a-VZ.js')


def zip_digest(archive):
    return hashlib.sha256(archive.read_bytes()).hexdigest()


def compat_args(*archives):
    return [arg for archive in archives for arg in
            ('--compat-zip', str(archive), '--compat-sha256', zip_digest(archive))]


def extract(archive, destination):
    with zipfile.ZipFile(archive) as z:
        z.extractall(destination)
    return destination/'alt-context'


def legacy_install(tmp_path, site, *, links=True):
    """Actual three-link shape, with a complete verified old graph available."""
    original = artifact(tmp_path, '0.0.36')
    with zipfile.ZipFile(original) as z:
        files = {n.removeprefix('alt-context/'): z.read(n) for n in z.namelist()}
    manifest = json.loads(files[DIST+'.vite/manifest.json'])
    for node, name in zip(('admin', 'lazy'), LEGACY_LINKS):
        previous = DIST+manifest[node]['file']
        manifest[node]['file'] = 'assets/'+name
        files[DIST+'assets/'+name] = files.pop(previous)
    manifest['lazy']['dynamicImports'] = ['attachment']
    manifest['attachment'] = {'file': 'assets/'+LEGACY_LINKS[2]}
    files[DIST+'assets/'+LEGACY_LINKS[2]] = b'exact attachment bytes'
    files[DIST+'.vite/manifest.json'] = json.dumps(manifest).encode()
    # This fixture constructs a published ZIP once, before any install/custody.
    with zipfile.ZipFile(original, 'w') as z:
        for name, data in files.items():
            z.writestr('alt-context/'+name, data)
    current_zip = artifact(tmp_path, '0.0.38')
    old = extract(original, tmp_path/'original-036')
    current = extract(current_zip, tmp_path/'deployed-038')
    with zipfile.ZipFile(original) as z:
        for name in z.namelist():
            relative = name.removeprefix('alt-context/')
            if relative.startswith(DIST+'assets/') and not (current/relative).exists():
                if links and Path(relative).name in LEGACY_LINKS:
                    (current/relative).symlink_to(old/relative)
                else:
                    (current/relative).write_bytes(z.read(name))
    (site[0]/'wp-content/plugins/alt-context').symlink_to(current)
    assert sum(p.is_symlink() for p in current.rglob('*')) == (3 if links else 0)
    return original, current_zip, old, current


def tree_state(root):
    """Include dotfile receipts, link identities and custody bytes in refusals."""
    if not root.exists():
        return None
    return {str(p.relative_to(root)): ('link', str(p.readlink()),
                                      zip_digest(p) if p.is_file() else None) if p.is_symlink()
            else ('dir', p.stat().st_mode) if p.is_dir()
            else ('file', p.stat().st_mode, zip_digest(p))
            for p in root.rglob('*')}


def refuse_unchanged(site, archive, *args):
    active = site[0]/'wp-content/plugins/alt-context'
    before = active.readlink(), tree_state(active.resolve()), tree_state(site[1])
    result = run(site, archive, *args, ok=False)
    assert (active.readlink(), tree_state(active.resolve()), tree_state(site[1])) == before
    # An unsupported-flag parser failure is not evidence of integrity validation.
    assert result.stdout.strip(), 'refusal must return a JSON error, not an unsupported CLI flag'
    assert json.loads(result.stdout).get('error'), result.stdout
    return json.loads(result.stdout)


def assert_graph_bytes(active, *archives):
    # Fixtures declare every dist/assets file, including multihop imports,
    # dynamic imports, CSS and image edges. Expected bytes come from ZIPs.
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                relative = name.removeprefix('alt-context/')
                if relative.startswith(DIST+'assets/'):
                    assert (active/relative).read_bytes() == z.read(name), relative
                    assert not (active/relative).is_symlink(), relative


def assert_custody_and_provenance(site, *archives):
    receipt = (site[0]/'wp-content/plugins/alt-context/.release-receipt.json').read_text()
    json.loads(receipt)
    for archive in archives:
        sha = zip_digest(archive)
        assert sha in receipt, 'receipt must record each supplied ZIP digest'
        custody = site[1]/'artifacts'/sha/'artifact.zip'
        assert custody.read_bytes() == archive.read_bytes()
        assert custody.stat().st_mode & 0o222 == 0


def test_qb_legacy_three_links_default_refused_unchanged(tmp_path, site):
    _, current, _, _ = legacy_install(tmp_path, site)
    refuse_unchanged(site, current)


@pytest.mark.parametrize('links', [True, False], ids=['three-links', 'regular-legacy-files'])
def test_qb_verified_compat_adoption_keeps_complete_graph(tmp_path, site, links):
    old, current, original, deployed = legacy_install(tmp_path, site, links=links)
    before = tree_state(original), tree_state(deployed)
    run(site, current, *compat_args(old))
    active = site[0]/'wp-content/plugins/alt-context'
    assert_graph_bytes(active, old, current)
    assert_custody_and_provenance(site, old, current)
    assert (tree_state(original), tree_state(deployed)) == before
    # Managed upgrades and rollback inherit all graphs without re-listing ZIPs.
    newer = artifact(tmp_path, '0.0.39')
    run(site, newer)
    run(site, newer, '--verify')
    assert_graph_bytes(active, old, current, newer)
    assert run(site, current, '--rollback')['rolled_back']
    assert_graph_bytes(active, old, current, newer)


def test_qb_uncovered_regular_legacy_files_refused_unchanged(tmp_path, site):
    _, current, _, _ = legacy_install(tmp_path, site, links=False)
    refuse_unchanged(site, current)


@pytest.mark.parametrize('bad', [
    'digest', 'zip-without-digest', 'digest-without-zip', 'unequal-counts',
    'corrupt-zip', 'incomplete-graph', 'unknown-link', 'wrong-link-bytes',
    'unknown-static-file', 'candidate-collision', 'compat-collision',
])
def test_qb_compat_integrity_refused_unchanged(tmp_path, site, bad):
    old, current, original, deployed = legacy_install(tmp_path, site)
    flags = compat_args(old)
    if bad == 'digest':
        flags[-1] = '0'*64
    elif bad == 'zip-without-digest':
        flags = ['--compat-zip', str(old)]
    elif bad == 'digest-without-zip':
        flags = ['--compat-sha256', zip_digest(old)]
    elif bad == 'unequal-counts':
        flags += ['--compat-zip', str(current)]
    elif bad in ('corrupt-zip', 'incomplete-graph'):
        broken = tmp_path/'invalid-compat.zip'
        if bad == 'corrupt-zip':
            broken.write_bytes(old.read_bytes()[:-20])
        else:
            with zipfile.ZipFile(old) as source, zipfile.ZipFile(broken, 'w') as dest:
                for name in source.namelist():
                    if not name.endswith('deep-stable.css'):
                        dest.writestr(name, source.read(name))
        flags = compat_args(broken)
    elif bad == 'unknown-link':
        (deployed/(DIST+'assets/undeclared.js')).symlink_to(original/(DIST+'assets/'+LEGACY_LINKS[0]))
    elif bad == 'wrong-link-bytes':
        # Declared path alone is insufficient; served bytes must match too.
        (original/(DIST+'assets/'+LEGACY_LINKS[0])).write_bytes(b'wrong served bytes')
    elif bad == 'unknown-static-file':
        (deployed/(DIST+'assets/undeclared.js')).write_bytes(b'unknown static asset')
    elif bad == 'candidate-collision':
        current = artifact(tmp_path, 'hotfix', **{DIST+'assets/'+LEGACY_LINKS[0]: 'different candidate bytes'})
    elif bad == 'compat-collision':
        conflict = artifact(tmp_path, 'conflict', **{DIST+'assets/shared-stable.js': 'different shared bytes'})
        flags += compat_args(conflict)
    refuse_unchanged(site, current, *flags)


def retired_tree(tmp_path, site):
    a, b, c = [artifact(tmp_path, v) for v in ('1', '2', '3')]
    run(site, a); run(site, b)
    active = site[0]/'wp-content/plugins/alt-context'
    # Model an already metadata-free external handoff; the original managed
    # tree, its receipt and its custody ZIPs remain intact in store1.
    external = tmp_path/'external-handoff'
    shutil.copytree(active.resolve(), external,
                    ignore=shutil.ignore_patterns('.release-receipt.json'))
    replacement = active.with_name('handoff-link')
    replacement.symlink_to(external); os.replace(replacement, active)
    assert_graph_bytes(active, a, b)
    return (site[0], tmp_path/'store2'), a, b, c, external


@pytest.mark.parametrize('coverage', ['none', 'current-only'])
def test_qb_metadata_free_handoff_incomplete_coverage_refused(tmp_path, site, coverage):
    fresh, a, b, c, external = retired_tree(tmp_path, site)
    original_store = tree_state(site[1])
    flags = [] if coverage == 'none' else compat_args(b)
    refuse_unchanged(fresh, c, *flags)
    assert_graph_bytes(external, a, b)
    assert tree_state(site[1]) == original_store


def test_qb_metadata_free_handoff_all_verified_graphs_survive(tmp_path, site):
    fresh, a, b, c, external = retired_tree(tmp_path, site)
    before = tree_state(external), tree_state(site[1])
    run(fresh, c, *compat_args(a, b))
    active = fresh[0]/'wp-content/plugins/alt-context'
    assert_graph_bytes(active, a, b, c)
    assert_custody_and_provenance(fresh, a, b, c)
    assert (tree_state(external), tree_state(site[1])) == before
    d = artifact(tmp_path, '4')
    run(fresh, d)
    run(fresh, d, '--verify')
    assert_graph_bytes(active, a, b, c, d)


def test_qb_cross_store_reap_refused_preserves_rollback(tmp_path, site):
    a, b = artifact(tmp_path, '1'), artifact(tmp_path, '2')
    first = run(site, a)
    second_site = site[0], tmp_path/'store2'
    second = run(second_site, b)
    assert second['previous'] == first['view']
    second_before = tree_state(second_site[1])
    # Exact escaped sequence: active B in store2; --reap B against store1.
    refuse_unchanged(site, b, '--reap')
    assert tree_state(second_site[1]) == second_before
    assert Path(first['view']).is_dir()
    assert json.loads((Path(first['view'])/'.release-receipt.json').read_text())['artifact_sha256'] == zip_digest(a)
    result = run(second_site, a, '--rollback')
    assert result['rolled_back'] and result['version'] == '1'
    assert Path(result['view']).parent == second_site[1]/'views'
    assert_graph_bytes(site[0]/'wp-content/plugins/alt-context', a, b)
    run(second_site, a, '--verify')


# Store capacity: default 8 managed views/custody ZIPs, explicit headroom <= 16.
CAPACITY = ('--capacity', '16')
FULL = 'artifact custody limit: operator retirement required'


@contextlib.contextmanager
def served(root):
    handler = lambda *args, **kw: http.server.SimpleHTTPRequestHandler(*args, directory=str(root), **kw)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join()


def assert_served(url, *archives):
    # Already-open pages fetch old modules over HTTP; compare ZIP bytes.
    for archive in archives:
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                relative = name.removeprefix('alt-context/')
                if relative.startswith(DIST+'assets/'):
                    with urllib.request.urlopen(url+'/wp-content/plugins/alt-context/'+relative) as response:
                        assert response.read() == z.read(name), relative


def assert_kept(root, before):
    after = tree_state(root)
    assert {path: after.get(path) for path in before} == before


def full_store_history(tmp_path, site):
    """Actual LocalWP shape: verified 0.0.36/0.0.38 adoption, then six managed
    promotions: 8 custody ZIPs, 7 views, active view inheriting 7 digests."""
    old, current, _, _ = legacy_install(tmp_path, site)
    run(site, current, *compat_args(old))
    history = [old, current]
    for number in range(1, 7):
        history.append(artifact(tmp_path, f'0.1.{number}'))
        run(site, history[-1])
    assert len(list((site[1]/'artifacts').iterdir())) == 8
    assert len(list((site[1]/'views').iterdir())) == 7
    receipt = json.loads((site[0]/'wp-content/plugins/alt-context/.release-receipt.json').read_text())
    assert len(receipt['compatibility_artifacts']) == 7
    return history


def test_explicit_capacity_admits_ninth_release_with_full_history(tmp_path, site):
    history = full_store_history(tmp_path, site)
    ninth = artifact(tmp_path, '0.2.0')
    active = site[0]/'wp-content/plugins/alt-context'
    unmanaged = [tree_state(tmp_path/name) for name in ('original-036', 'deployed-038')]
    with served(site[0]) as url:
        # The default, spelled or implied, keeps refusing the ninth artifact.
        for flags in ((), ('--capacity', '8')):
            error = refuse_unchanged(site, ninth, '--site-url', url, *flags)
            assert error == {'status': 'error', 'error': FULL, 'capacity': 8}
        before = tree_state(site[1])
        result = run(site, ninth, *CAPACITY, '--site-url', url)
        assert result['capacity'] == 16 and result['http_verified'] and result['version'] == '0.2.0'
        assert set(result['compatibility_artifacts']) == {zip_digest(a) for a in history}
        # Headroom is per invocation: the receipt format stores no policy.
        assert 'capacity' not in json.loads((active/'.release-receipt.json').read_text())
        assert_kept(site[1], before)
        assert_custody_and_provenance(site, *history, ninth)
        assert_graph_bytes(active, *history, ninth)
        assert_served(url, *history, ninth)
        published = tree_state(site[1])
        verified = run(site, ninth, '--verify', '--site-url', url, *CAPACITY)
        assert verified['view'] == result['view'] and verified['http_verified']
        assert run(site, ninth)['view'] == result['view']
        assert tree_state(site[1]) == published
        # Rollback inherits nine digests, so it needs the same explicit capacity.
        previous = history[-1]
        error = refuse_unchanged(site, previous, '--rollback', '--site-url', url)
        assert error['error'] == 'compatibility artifact limit exceeded'
        back = run(site, previous, '--rollback', *CAPACITY, '--site-url', url)
        assert back['rolled_back'] and back['http_verified'] and back['capacity'] == 16
        assert back['artifact_sha256'] == zip_digest(previous) and back['previous'] == result['view']
        assert_kept(site[1], published)
        assert_custody_and_provenance(site, *history, ninth)
        assert_graph_bytes(active, *history, ninth)
        assert_served(url, *history, ninth)
        reaped = run(site, previous, '--reap', *CAPACITY)
        assert reaped['reaped_views'] == [] and reaped['retention_limit'] == 16
    assert len(list((site[1]/'views').iterdir())) == 9
    assert len(list((site[1]/'artifacts').iterdir())) == 9
    assert [tree_state(tmp_path/name) for name in ('original-036', 'deployed-038')] == unmanaged


def test_explicit_capacity_cross_store_keeps_full_old_store(tmp_path, site):
    history = full_store_history(tmp_path, site)
    ninth = artifact(tmp_path, '0.2.0')
    old_store = tree_state(site[1])
    fresh = site[0], tmp_path/'store2'
    # Another store inherits all eight custody ZIPs: a hop is no quota reset.
    assert refuse_unchanged(fresh, ninth)['error'] == FULL
    result = run(fresh, ninth, *CAPACITY)
    assert Path(result['view']).parent == fresh[1]/'views'
    assert_custody_and_provenance(fresh, *history, ninth)
    active = site[0]/'wp-content/plugins/alt-context'
    assert_graph_bytes(active, *history, ninth)
    back = run(fresh, history[-1], '--rollback', *CAPACITY)
    assert back['rolled_back'] and Path(back['view']).parent == fresh[1]/'views'
    run(fresh, history[-1], '--verify')
    assert_graph_bytes(active, *history, ninth)
    refuse_unchanged(site, history[-1], '--reap', *CAPACITY)
    assert tree_state(site[1]) == old_store


def test_capacity_hard_bound_refuses_seventeenth_unchanged(tmp_path, site):
    releases = [artifact(tmp_path, f'1.{number}') for number in range(1, 18)]
    for release in releases[:16]:
        assert run(site, release, *CAPACITY)['capacity'] == 16
    assert len(list((site[1]/'artifacts').iterdir())) == 16
    assert len(list((site[1]/'views').iterdir())) == 16
    assert refuse_unchanged(site, releases[16], *CAPACITY)['error'] == FULL
    assert 'capacity' in refuse_unchanged(site, releases[16], '--capacity', '17')['error']
    # Refusal precedes reading inherited ZIPs past N, bounding held custody
    # bytes; the oldest (16th inherited) ZIP is never opened by the 17th.
    oldest = site[1]/'artifacts'/zip_digest(releases[0])
    oldest.chmod(0o755); (oldest/'artifact.zip').chmod(0o644)
    (oldest/'artifact.zip').write_bytes(b'beyond capacity')
    assert refuse_unchanged(site, releases[16], *CAPACITY)['error'] == FULL
    assert_graph_bytes(site[0]/'wp-content/plugins/alt-context', *releases[:16])
    # Supplied compatibility ZIPs share the bound: at most N-1 beside the primary.
    run(site, releases[16], '--dry-run', *CAPACITY, *compat_args(*releases[1:16]))
    limit = 'compatibility artifact limit exceeded'
    assert refuse_unchanged(site, releases[16], '--dry-run', *CAPACITY, *compat_args(*releases[:16]))['error'] == limit
    assert refuse_unchanged(site, releases[16], '--dry-run', *compat_args(*releases[8:16]))['error'] == limit


@pytest.mark.parametrize('value', ['7', '17', '0', '-1', '9.5', '16.0', '+16', ' 16', '１６', 'sixteen', ''])
def test_invalid_capacity_refused_unchanged(tmp_path, site, value):
    run(site, artifact(tmp_path, '1'))
    error = refuse_unchanged(site, artifact(tmp_path, '2'), '--capacity', value)
    assert 'capacity' in error
    assert error['capacity'] is None
    assert error == {'status': 'error', 'error': 'invalid --capacity: integer 8..16 required', 'capacity': None}
