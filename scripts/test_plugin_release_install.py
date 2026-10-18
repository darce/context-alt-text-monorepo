"""Synthetic Linux promotion tests; no WordPress, database or build required."""
import hashlib
import http.server
import json
import os
from pathlib import Path
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
    result = subprocess.run(['python3', str(CLI), '--wp-path', str(wp), '--store', str(store), '--zip', str(archive), '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), *args], capture_output=True, text=True)
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
