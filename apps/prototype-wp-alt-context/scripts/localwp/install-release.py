#!/usr/bin/env python3
"""Promote a canonical prebuilt ZIP. Linux, Python standard library only."""
import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
import uuid

DIST = 'public/assets/dist/'
RECEIPT = '.release-receipt.json'
MAX_VIEWS = 8
MAX_BYTES = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(name):
    require(isinstance(name, str) and name and '\\' not in name and '%' not in name and '?' not in name and '#' not in name, 'unsafe path')
    p = PurePosixPath(name)
    require(not p.is_absolute() and all(x not in ('', '.', '..') for x in name.split('/')), 'unsafe path: '+name)
    return name


def graph(root):
    manifest = root / (DIST+'.vite/manifest.json')
    if not manifest.is_file():
        manifest = root / (DIST+'manifest.json')
    require(manifest.resolve().is_relative_to(root.resolve()), 'escaping manifest')
    raw = manifest.read_bytes()
    nodes = json.loads(raw)
    require(isinstance(nodes, dict) and nodes, 'empty manifest')
    entries = [k for k, v in nodes.items() if isinstance(v, dict) and v.get('isEntry')]
    require(entries, 'manifest has no entries')
    paths, visited = set(), set()

    def visit(key):
        if key in visited:
            return
        visited.add(key)
        require(key in nodes and isinstance(nodes[key], dict), 'missing manifest import: '+str(key))
        node = nodes[key]
        paths.add(DIST+safe(node['file']))
        for field in ('css', 'assets'):
            require(isinstance(node.get(field, []), list), 'invalid asset list')
            for path in node.get(field, []):
                paths.add(DIST+safe(path))
        for field in ('imports', 'dynamicImports'):
            require(isinstance(node.get(field, []), list), 'invalid imports')
            for child in node.get(field, []):
                require(isinstance(child, str), 'invalid import')
                visit(child)
    # Validate all nodes, including secondary entries, rather than entry JS alone.
    for key in nodes:
        visit(key)
    result = {}
    for path in sorted(paths):
        target = root/path
        require(target.resolve().is_relative_to(root.resolve()) and target.is_file(), 'missing/escaping asset: '+path)
        result[path] = digest(target.read_bytes())
    return {'manifest_sha256': digest(raw), 'entries': entries, 'graph': result}


def validate(root):
    header = (root/'alt-context.php').read_text()
    match = re.search(r'^\s*\*\s*Version:\s*([^\r\n]+)', header, re.M)
    require(header.lstrip().startswith('<?php') and 'Plugin Name:' in header and match, 'invalid plugin PHP header')
    require((root/'vendor/autoload.php').read_bytes().lstrip().startswith(b'<?php'), 'missing production autoload')
    for path in ('.env', '.env.local', '.env.production', '.env.development', 'node_modules', 'tests', 'vendor/phpunit', 'vendor/squizlabs/php_codesniffer', 'vendor/wp-coding-standards/wpcs'):
        require(not (root/path).exists(), 'nonproduction input: '+path)
    for path in ('alt-context.php', 'vendor/autoload.php'):
        lint = subprocess.run(['php', '-n', '-l', str(root/path)], capture_output=True, timeout=10)
        require(lint.returncode == 0, 'PHP syntax check failed: '+path)
    return {'version': match.group(1).strip(), **graph(root)}


def unpack(data, root):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        require(len(infos) <= 30000 and sum(i.file_size for i in infos) <= MAX_BYTES, 'ZIP exceeds limits')
        seen = set()
        for item in infos:
            require('\x00' not in item.orig_filename, 'NUL in ZIP path')
            name = item.filename[:-1] if item.is_dir() else item.filename
            safe(name)
            require(name == 'alt-context' or name.startswith('alt-context/'), 'unexpected ZIP slug')
            require(name not in seen, 'duplicate ZIP path')
            seen.add(name)
            mode = item.external_attr >> 16
            require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), 'ZIP special file/symlink')
            if name == 'alt-context':
                require(item.is_dir(), 'invalid ZIP root')
                continue
            require(name != 'alt-context/'+RECEIPT, 'reserved installer metadata')
            target = root/name[len('alt-context/'):]
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))  # CRC checked by zipfile


def inventory(root, max_bytes=MAX_BYTES * (MAX_VIEWS + 1)):
    result = {}
    total = 0
    for p in root.rglob('*'):
        require(not p.is_symlink(), 'symlink inside artifact/view')
        if p.is_file() and p.name != RECEIPT:
            total += p.stat().st_size
            require(total <= max_bytes and len(result) < 30000 * (MAX_VIEWS + 1), 'installed tree exceeds bounds')
            result[str(p.relative_to(root))] = digest(p.read_bytes())
    return result


def receipt(root):
    p = root/RECEIPT
    return json.loads(p.read_text()) if p.is_file() else None


def check_view(root):
    r = receipt(root)
    require(r and inventory(root) == r['files'], 'view identity mismatch')
    identity = validate(root)
    require(all(identity[key] == r[key] for key in identity), 'manifest/header identity mismatch')
    require(all(r['files'].get(path) == sha for path, sha in r['compatibility'].items()), 'compatibility identity mismatch')
    return r


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('HTTP redirect refused')


def readback(root, r, site_url):
    if not site_url:
        return False
    parsed = urllib.parse.urlsplit(site_url)
    require(parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment, 'invalid site URL')
    opener = urllib.request.build_opener(NoRedirect)
    deadline = time.monotonic() + 30
    for path, expected in r['compatibility'].items():
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'HTTP readback exceeded 30s budget')
        url = site_url.rstrip('/')+'/wp-content/plugins/alt-context/'+urllib.parse.quote(path, safe='/')
        with opener.open(url, timeout=min(3, remaining)) as response:
            require(response.status == 200 and digest(response.read((root/path).stat().st_size+1)) == expected, 'served asset identity mismatch: '+path)
    return True


def reap(store, active):
    """Conservative orphan cleanup; never retire a compatibility/rollback root."""
    views = store/'views'
    records = {p: check_view(p) for p in views.iterdir()}
    protected = {active.resolve()}
    protected.update(Path(r['previous']) for r in records.values() if r['previous'])
    removed = []
    for path in records:
        require(path.resolve().parent == views.resolve() and not path.is_symlink(), 'unsafe view custody')
        if path not in protected:
            for child in path.rglob('*'):
                if child.is_dir():
                    child.chmod(0o755)
            path.chmod(0o755)
            shutil.rmtree(path)
            removed.append(str(path))
    # ZIP custody is intentionally not reaped: it is small compared with views,
    # and may be retained as release evidence outside deployment references.
    return {'reaped_views': removed, 'retention_limit': MAX_VIEWS}


def swap(active, destination):
    temporary = active.with_name('.alt-context-promotion-'+str(os.getpid()))
    try:
        temporary.symlink_to(destination)
        os.replace(temporary, active)
    finally:
        temporary.unlink(missing_ok=True)


def execute(args):
    wp, store = Path(args.wp_path).resolve(), Path(args.store).resolve()
    require((wp/'wp-load.php').is_file(), 'invalid WordPress root')
    require(not store.is_relative_to(wp) and not wp.is_relative_to(store), 'store must be outside WordPress')
    active = wp/'wp-content/plugins/alt-context'
    require(active.parent.is_dir(), 'missing plugins directory')
    require(not active.exists() or active.is_symlink(), 'existing directory requires operator migration to a stable symlink')
    require(Path(args.zip).stat().st_size <= MAX_BYTES, 'ZIP exceeds limits')
    data = Path(args.zip).read_bytes()
    require(len(data) <= MAX_BYTES and re.fullmatch('[0-9a-fA-F]{64}', args.sha256) and digest(data) == args.sha256.lower(), 'ZIP SHA256 mismatch')
    # Candidate validation precedes all site/store mutation.
    with tempfile.TemporaryDirectory(prefix='acx-validate-') as scratch:
        candidate = Path(scratch)/'plugin'; candidate.mkdir()
        unpack(data, candidate)
        identity = {'artifact_sha256': digest(data), **validate(candidate)}
        if args.dry_run:
            return {**identity, 'dry_run': True, 'scope': 'candidate validation only; site compatibility checked under install lock'}
        # Site-local lock serializes even callers supplying different stores.
        with (active.parent/'.alt-context-release.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = str(active.resolve()) if active.is_symlink() else None
            require(not previous or Path(previous).is_dir(), 'dangling active target')
            old = receipt(Path(previous)) if previous else None
            if args.reap:
                require(old and old['artifact_sha256'] == identity['artifact_sha256'], 'reap requires active candidate')
                require(json.loads((store/'site.json').read_text()) == str(wp), 'store belongs to another site')
                return reap(store, active)
            if args.rollback:
                require(old and old['previous'] and Path(old['previous']).is_dir(), 'no rollback target')
                prior_root = Path(old['previous'])
                if receipt(prior_root):
                    prior = check_view(prior_root)
                    require(prior['artifact_sha256'] == identity['artifact_sha256'], 'rollback ZIP differs from previous install')
                else:
                    require(inventory(prior_root) == inventory(candidate), 'rollback ZIP differs from original installed bytes')
                # Build a new view retaining BOTH graphs, also on rollback.
            if args.verify or (old and old['artifact_sha256'] == identity['artifact_sha256']):
                require(previous, 'nothing installed')
                r = check_view(Path(previous))
                require(r['artifact_sha256'] == identity['artifact_sha256'], 'active artifact differs')
                require((store/'artifacts'/identity['artifact_sha256']/'artifact.zip').read_bytes() == data, 'custody ZIP differs')
                return {**r, 'http_verified': readback(active, r, args.site_url)}
            compatibility = dict(identity['graph'])
            prior_tree = None
            if previous:
                if not old:
                    prior_tree = inventory(Path(previous), MAX_BYTES)
                prior_graph = graph(Path(previous))['graph']
                if old:
                    check_view(Path(previous))
                    prior_graph.update(old['compatibility'])
                for path, sha in prior_graph.items():
                    existing = candidate/path
                    require(not existing.exists() or digest(existing.read_bytes()) == sha, 'asset name collision: '+path)
                    compatibility[path] = sha
                    if not existing.exists():
                        existing.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(Path(previous)/path, existing)
            store.mkdir(parents=True, exist_ok=True)
            owner = store/'site.json'
            if owner.exists():
                require(json.loads(owner.read_text()) == str(wp), 'store belongs to another site')
            else:
                owner.write_text(json.dumps(str(wp)))
            views = store/'views'; views.mkdir(exist_ok=True)
            require(len(list(views.iterdir())) < MAX_VIEWS, 'retention limit: operator retirement required')
            artifacts = store/'artifacts'
            require(not artifacts.exists() or len(list(artifacts.iterdir())) < MAX_VIEWS or (artifacts/identity['artifact_sha256']).exists(), 'artifact custody limit: operator retirement required')
            custody = artifacts/identity['artifact_sha256']
            custody.parent.mkdir(exist_ok=True)
            if custody.exists():
                require((custody/'artifact.zip').read_bytes() == data, 'custody identity mismatch')
            else:
                with tempfile.TemporaryDirectory(dir=custody.parent) as temp:
                    staged = Path(temp)/'custody'; staged.mkdir()
                    (staged/'artifact.zip').write_bytes(data)
                    os.rename(staged, custody)
                (custody/'artifact.zip').chmod(0o444)
                custody.chmod(0o555)
            destination = views/(identity['artifact_sha256']+'-'+uuid.uuid4().hex)
            with tempfile.TemporaryDirectory(dir=views) as temp:
                staged = Path(temp)/'view'
                shutil.copytree(candidate, staged)
                r = {**identity, 'view': str(destination), 'previous': previous, 'previous_identity': old['artifact_sha256'] if old else (digest(json.dumps(prior_tree, sort_keys=True).encode()) if previous else None), 'compatibility': compatibility, 'files': inventory(staged), 'runtime_refresh': 'operator: exact site PHP-FPM service; installer does not refresh runtime'}
                (staged/RECEIPT).write_text(json.dumps(r, sort_keys=True, indent=2)+'\n')
                for p in staged.rglob('*'):
                    p.chmod(0o555 if p.is_dir() else 0o444)
                os.rename(staged, destination)
                destination.chmod(0o555)
            swap(active, destination)
            try:
                check_view(active)
                verified = readback(active, r, args.site_url)
            except Exception:
                if previous:
                    swap(active, previous)
                else:
                    active.unlink()
                raise
            return {**r, 'rolled_back': args.rollback, 'http_verified': verified}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('wp-path', 'store', 'zip', 'sha256'):
        parser.add_argument('--'+name, required=True)
    mode = parser.add_mutually_exclusive_group()
    for name in ('dry-run', 'verify', 'rollback', 'reap'):
        mode.add_argument('--'+name, action='store_true')
    parser.add_argument('--site-url', help='WordPress URL; compare every retained asset byte, no redirects, 3s/request')
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), sort_keys=True))
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': str(error)}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
