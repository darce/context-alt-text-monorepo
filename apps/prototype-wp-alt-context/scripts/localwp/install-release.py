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
MAX_VIEWS = 8  # default store capacity; also sizes the fixed byte/entry ceilings
MAX_CAPACITY = 16  # hard bound for explicit --capacity operator headroom
MAX_BYTES = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_file(path, limit=MAX_BYTES, follow_symlink=False):
    """Bound reads even for operator inputs: never block on a device/FIFO."""
    flags = os.O_RDONLY | os.O_NONBLOCK
    if not follow_symlink:
        flags |= os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, 'nonregular/oversized file: '+str(path))
        data = stream.read(limit+1)
        require(len(data) <= limit, 'file exceeds bounds: '+str(path))
        return data


def capacity(value):
    """Exact decimal 8..16 only: no signs, spaces, decimals or non-ASCII digits."""
    require(value in [str(n) for n in range(MAX_VIEWS, MAX_CAPACITY+1)],
            'invalid --capacity: integer '+str(MAX_VIEWS)+'..'+str(MAX_CAPACITY)+' required')
    return int(value)


def safe(name):
    require(isinstance(name, str) and name and '\\' not in name and '%' not in name and '?' not in name and '#' not in name, 'unsafe path')
    p = PurePosixPath(name)
    require(not p.is_absolute() and all(x not in ('', '.', '..') for x in name.split('/')), 'unsafe path: '+name)
    return name


def graph(root, verified=None):
    manifest = root / (DIST+'.vite/manifest.json')
    if not manifest.is_file():
        manifest = root / (DIST+'manifest.json')
    require(manifest.resolve().is_relative_to(root.resolve()), 'escaping manifest')
    raw = read_file(manifest)
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
        if verified and path in verified:
            sha, source = verified[path]
            require(digest(read_file(target, source.stat().st_size, follow_symlink=True)) == sha, 'verified asset differs: '+path)
            result[path] = sha
        else:
            require(target.resolve().is_relative_to(root.resolve()) and target.is_file(), 'missing/escaping asset: '+path)
            result[path] = digest(read_file(target))
    return {'manifest_sha256': digest(raw), 'entries': entries, 'graph': result}


def validate(root, verified=None):
    header = read_file(root/'alt-context.php').decode()
    match = re.search(r'^\s*\*\s*Version:\s*([^\r\n]+)', header, re.M)
    require(header.lstrip().startswith('<?php') and 'Plugin Name:' in header and match, 'invalid plugin PHP header')
    require(read_file(root/'vendor/autoload.php').lstrip().startswith(b'<?php'), 'missing production autoload')
    for path in ('.env', '.env.local', '.env.production', '.env.development', 'node_modules', 'tests', 'vendor/phpunit', 'vendor/squizlabs/php_codesniffer', 'vendor/wp-coding-standards/wpcs'):
        require(not (root/path).exists(), 'nonproduction input: '+path)
    for path in ('alt-context.php', 'vendor/autoload.php'):
        lint = subprocess.run(['php', '-n', '-l', str(root/path)], capture_output=True, timeout=10)
        require(lint.returncode == 0, 'PHP syntax check failed: '+path)
    return {'version': match.group(1).strip(), **graph(root, verified)}


def unpack(data, root, budget=MAX_BYTES):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        size = sum(i.file_size for i in infos)
        require(len(infos) <= 30000 and size <= min(MAX_BYTES, budget), 'ZIP exceeds limits')
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
        return size


def inventory(root, max_bytes=MAX_BYTES * (MAX_VIEWS + 1), verified=None):
    result = {}
    total = count = 0
    for p in root.rglob('*'):
        count += 1
        require(count <= 30000 * (MAX_VIEWS + 1), 'installed tree exceeds bounds')
        name = str(p.relative_to(root))
        mode = p.lstat().st_mode
        if stat.S_ISLNK(mode):
            require(verified and name in verified, 'symlink inside artifact/view')
            sha, source = verified[name]
            data = read_file(p, min(source.stat().st_size, max_bytes-total), follow_symlink=True)
            require(digest(data) == sha, 'verified asset differs: '+name)
        elif stat.S_ISDIR(mode):
            continue
        else:
            require(stat.S_ISREG(mode), 'special file inside artifact/view')
            if name == RECEIPT:
                continue
            data = read_file(p, min(MAX_BYTES, max_bytes-total))
        total += len(data)
        result[name] = digest(data)
    return result


def unmanaged_inventory(root, verified, artifact_files, primary=None):
    """Verify metadata by ZIP inventory, but authorize links by static graph."""
    files = inventory(root, MAX_BYTES, verified)
    identity = validate(root, verified)
    known_versions = [known for version, known in artifact_files if version == identity['version']]
    if primary is None and known_versions:
        require(any(all(files.get(path) == sha for path, sha in known.items()) and
                    all(path in known or path.startswith(DIST) for path in files) for known in known_versions),
                'installed primary differs from verified artifact')
    if primary is not None:
        require(all(files.get(path) == sha for path, sha in primary.items()) and
                all(path in primary or (path.startswith(DIST) and path in verified and
                                        verified[path][0] == sha) for path, sha in files.items()),
                'rollback ZIP differs from original installed bytes')
    declared = {**identity['graph'], **{path: sha for path, (sha, _) in verified.items()}}
    manifest = DIST+'.vite/manifest.json' if (root/(DIST+'.vite/manifest.json')).is_file() else DIST+'manifest.json'
    for path, sha in files.items():
        if path.startswith(DIST) and path != manifest:
            require(declared.get(path) == sha or any(known.get(path) == sha for _, known in artifact_files),
                    'unverified legacy asset; supply all retained --compat-zip graphs: '+path)
    return files, identity['graph']


def receipt(root):
    p = root/RECEIPT
    return json.loads(read_file(p)) if p.exists() or p.is_symlink() else None


def carry(candidate, compatibility, assets):
    """Merge complete declared graphs; a candidate file always wins or refuses."""
    files = inventory(candidate)
    total = sum((candidate/path).stat().st_size for path in files)
    for path, (sha, source) in assets.items():
        existing = candidate/path
        require(not existing.exists() or digest(read_file(existing)) == sha, 'asset name collision: '+path)
        compatibility[path] = sha
        if not existing.exists():
            require(len(files) < 30000 * (MAX_VIEWS + 1), 'installed tree exceeds bounds')
            data = read_file(source, min(MAX_BYTES, MAX_BYTES * (MAX_VIEWS + 1)-total))
            require(digest(data) == sha, 'compatibility source changed: '+path)
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_bytes(data)
            total += len(data)
            files[path] = sha


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


def reap(store, active, limit):
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
    return {'reaped_views': removed, 'retention_limit': limit}


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
    require(len(args.compat_zip) == len(args.compat_sha256), 'compat ZIP/SHA256 counts differ')
    require(len(args.compat_zip) < args.capacity, 'compatibility artifact limit exceeded')
    data = read_file(Path(args.zip))
    require(len(data) <= MAX_BYTES and re.fullmatch('[0-9a-fA-F]{64}', args.sha256) and digest(data) == args.sha256.lower(), 'ZIP SHA256 mismatch')
    # Candidate validation precedes all site/store mutation.
    with tempfile.TemporaryDirectory(prefix='acx-validate-') as scratch:
        candidate = Path(scratch)/'plugin'; candidate.mkdir()
        expanded = unpack(data, candidate)
        identity = {'artifact_sha256': digest(data), **validate(candidate)}
        primary_files = inventory(candidate)
        artifact_files = [(identity['version'], primary_files)]
        archives = {identity['artifact_sha256']: data}
        verified, compatibility_artifacts = {}, []
        compatibility = dict(identity['graph'])
        for number, (path, expected) in enumerate(zip(args.compat_zip, args.compat_sha256)):
            prior_data = read_file(Path(path))
            sha = digest(prior_data)
            require(re.fullmatch('[0-9a-fA-F]{64}', expected) and sha == expected.lower(), 'compat ZIP SHA256 mismatch')
            root = Path(scratch)/('compat-'+str(number)); root.mkdir()
            expanded += unpack(prior_data, root, MAX_BYTES * MAX_VIEWS-expanded)
            prior = validate(root)
            artifact_files.append((prior['version'], inventory(root)))
            for name, asset_sha in prior['graph'].items():
                require(name not in verified or verified[name][0] == asset_sha, 'asset name collision: '+name)
                verified[name] = (asset_sha, root/name)
            archives[sha] = prior_data
            if sha != identity['artifact_sha256'] and sha not in compatibility_artifacts:
                compatibility_artifacts.append(sha)
        carry(candidate, compatibility, verified)
        if args.dry_run:
            return {**identity, 'compatibility_artifacts': compatibility_artifacts, 'dry_run': True, 'scope': 'candidate validation only; site compatibility checked under install lock'}
        # Site-local lock serializes even callers supplying different stores.
        with (active.parent/'.alt-context-release.lock').open('a') as lock:
            deadline = time.monotonic()+10
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    require(time.monotonic() < deadline, 'site install lock exceeded 10s budget')
                    time.sleep(0.05)
            previous = str(active.resolve()) if active.is_symlink() else None
            require(not previous or Path(previous).is_dir(), 'dangling active target')
            old = receipt(Path(previous)) if previous else None
            if args.reap:
                require(old and old['artifact_sha256'] == identity['artifact_sha256'], 'reap requires active candidate')
                require(Path(previous).parent == store/'views', 'reap requires active view in selected store/views')
                require(json.loads(read_file(store/'site.json')) == str(wp), 'store belongs to another site')
                return reap(store, active, args.capacity)
            if args.rollback:
                require(old and old['previous'] and Path(old['previous']).is_dir(), 'no rollback target')
                prior_root = Path(old['previous'])
                if receipt(prior_root):
                    prior = check_view(prior_root)
                    require(prior['artifact_sha256'] == identity['artifact_sha256'], 'rollback ZIP differs from previous install')
                else:
                    unmanaged_inventory(prior_root, verified, artifact_files, primary_files)
                # Build a new view retaining BOTH graphs, also on rollback.
            if args.verify or (old and old['artifact_sha256'] == identity['artifact_sha256'] and not args.compat_zip):
                require(previous, 'nothing installed')
                r = check_view(Path(previous))
                require(r['artifact_sha256'] == identity['artifact_sha256'], 'active artifact differs')
                require(read_file(store/'artifacts'/identity['artifact_sha256']/'artifact.zip') == data, 'custody ZIP differs')
                require(all(r['compatibility'].get(path) == sha for path, sha in compatibility.items()), 'active compatibility differs')
                return {**r, 'http_verified': readback(active, r, args.site_url)}
            prior_tree = None
            if previous:
                if not old:
                    prior_tree, prior_graph = unmanaged_inventory(Path(previous), verified, artifact_files)
                if old:
                    check_view(Path(previous))
                    prior_graph = graph(Path(previous))['graph']
                    prior_graph.update(old['compatibility'])
                    # A managed view's receipt carries the graph automatically.
                    # Keep its verified custody when changing site-bound stores.
                    inherited = [old['artifact_sha256'], *old.get('compatibility_artifacts', [])]
                    require(len(inherited) <= args.capacity, 'compatibility artifact limit exceeded')
                    for sha in inherited:
                        require(re.fullmatch('[0-9a-f]{64}', sha), 'invalid custody digest')
                        if sha not in archives:
                            # Refuse before reading: at most `capacity` ZIPs are held.
                            require(len(archives) < args.capacity, 'artifact custody limit: operator retirement required')
                            prior_data = read_file(Path(previous).parent.parent/'artifacts'/sha/'artifact.zip')
                            require(digest(prior_data) == sha, 'inherited custody ZIP differs')
                            archives[sha] = prior_data
                        if sha != identity['artifact_sha256'] and sha not in compatibility_artifacts:
                            compatibility_artifacts.append(sha)
                sources = {path: (sha, verified[path][1] if path in verified else Path(previous)/path) for path, sha in prior_graph.items()}
                carry(candidate, compatibility, sources)
            require(len(archives) <= args.capacity, 'artifact custody limit: operator retirement required')
            store.mkdir(parents=True, exist_ok=True)
            owner = store/'site.json'
            if owner.exists():
                require(json.loads(read_file(owner)) == str(wp), 'store belongs to another site')
            else:
                owner.write_text(json.dumps(str(wp)))
            views = store/'views'; views.mkdir(exist_ok=True)
            require(len(list(views.iterdir())) < args.capacity, 'retention limit: operator retirement required')
            artifacts = store/'artifacts'
            retained = {p.name for p in artifacts.iterdir()} if artifacts.exists() else set()
            require(len(retained | archives.keys()) <= args.capacity, 'artifact custody limit: operator retirement required')
            artifacts.mkdir(exist_ok=True)
            for sha, archive_data in archives.items():
                custody = artifacts/sha
                if custody.exists():
                    require(read_file(custody/'artifact.zip') == archive_data, 'custody identity mismatch')
                else:
                    with tempfile.TemporaryDirectory(dir=artifacts) as temp:
                        staged = Path(temp)/'custody'; staged.mkdir()
                        (staged/'artifact.zip').write_bytes(archive_data)
                        os.rename(staged, custody)
                    (custody/'artifact.zip').chmod(0o444)
                    custody.chmod(0o555)
            destination = views/(identity['artifact_sha256']+'-'+uuid.uuid4().hex)
            with tempfile.TemporaryDirectory(dir=views) as temp:
                staged = Path(temp)/'view'
                shutil.copytree(candidate, staged)
                r = {**identity, 'view': str(destination), 'previous': previous, 'previous_identity': old['artifact_sha256'] if old else (digest(json.dumps(prior_tree, sort_keys=True).encode()) if previous else None), 'compatibility': compatibility, 'compatibility_artifacts': compatibility_artifacts, 'files': inventory(staged), 'runtime_refresh': 'operator: exact site PHP-FPM service; installer does not refresh runtime'}
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
    parser.add_argument('--compat-zip', action='append', default=[], help='complete prior canonical ZIP; repeat in digest order for metadata-free handoff')
    parser.add_argument('--compat-sha256', action='append', default=[], help='expected SHA256 paired in order with --compat-zip')
    mode = parser.add_mutually_exclusive_group()
    for name in ('dry-run', 'verify', 'rollback', 'reap'):
        mode.add_argument('--'+name, action='store_true')
    parser.add_argument('--site-url', help='WordPress URL; compare every retained asset byte, no redirects, 3s/request')
    parser.add_argument('--capacity', default=str(MAX_VIEWS), metavar='N',
                        help='store capacity: max managed views and custody ZIPs (default %(default)s); explicit '
                             'operator headroom up to '+str(MAX_CAPACITY)+', never persisted, so repeat it for '
                             'later promotion/rollback; byte and entry ceilings do not change')
    args = parser.parse_args()
    effective = {}
    try:
        args.capacity = capacity(args.capacity)
        effective = {'capacity': args.capacity}
        print(json.dumps({**execute(args), **effective}, sort_keys=True))
    except Exception as error:
        print(json.dumps({'status': 'error', 'error': str(error), **effective}))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
