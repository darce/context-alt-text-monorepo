"""Rebind the gated incumbent pilot recipe to the durable source root (BAKEOFF-INC-REBIND-20261020, RLSE-21).

Promotes the stored, already-gated prospective artifact with exactly four substitutions. No generator is restored.
"""
import argparse
import ast
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
QWEN_RUNNER = HERE.parent / 'qwen-ab' / 'run_qwen_cohort_operation.py'
SCHEMA = 'incumbent-ab-prospective-recipe/v2'
STATUS = 'PREPARED_REQUIRES_INDEPENDENT_GATE_AND_PILOT'
SOURCE_RECIPE_SHA256 = '603f1a9b1e65f5c1ade9e3753d7afad5099ece8e872ab3bb2cac167a7bdac3f5'
OLD_SUBJECT = 'c8ddf61000475653c4a69ef31ae25ebdedd1a47e'
SOURCE = 'ab94e904ca25e2e031ad241f2600aa0406201c15'
KEY = 'feature-bakerounds-20261017-raw-auth-ini-3255682b'
WORKBAY_ROOT = '/home/gate/workbay-sandbox'
CANON = 'v0.26.2 RLSE-21 FLOW-01'
PROSPECTIVE_NAME = 'incumbent-pilot-durable.prospective.json'
REMOTE_NAME = 'incumbent-pilot-durable.remote.py'
FORBIDDEN = ('KEY', 'workbay-sandbox', 'venv-lane', 'c8ddf610')
# The prospective is the consumer's commit marker, so it is published last and rolled back first.
PUBLISH_ORDER = (REMOTE_NAME, PROSPECTIVE_NAME)


def load_runner():
    spec = importlib.util.spec_from_file_location('qwen_cohort_operation', QWEN_RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load_runner()
SOURCE_ROOT = runner.SOURCE_ROOT
REPO_EXPR = runner.REPO_EXPR
PYTHON_EXPR = runner.PYTHON_EXPR


class Refusal(Exception):
    pass


def need(ok, why):
    if not ok:
        raise Refusal(why)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_prospective(path):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        raise Refusal(f'cannot read prospective JSON {path}: {e}')
    need(isinstance(doc, dict), 'prospective input must be a JSON object')
    p = doc['prospective'] if 'schema' not in doc and 'prospective' in doc else doc
    need(isinstance(p, dict), 'prospective must be a JSON object')
    return p


def validate_prospective(p):
    need(p.get('schema') == SCHEMA, f'schema is not {SCHEMA}')
    need(p.get('status') == STATUS, f'status is not {STATUS}')
    need(p.get('execution_started') is False, 'execution_started must be false')
    recipe = p.get('executable_recipe')
    need(isinstance(recipe, str), 'executable_recipe must be a string')
    try:
        encoded = recipe.encode('utf-8')
    except UnicodeEncodeError as e:
        raise Refusal(f'executable_recipe is not encodable as UTF-8: {e}') from e
    digest = sha256(encoded)
    need(p.get('recipe_sha256') == digest, 'recipe_sha256 does not match executable_recipe')
    need(digest == SOURCE_RECIPE_SHA256, f'recipe digest {digest} is not the pinned incumbent recipe')
    contract = p.get('admission_contract')
    need(isinstance(contract, dict) and contract.get('reviewed_subject') == OLD_SUBJECT,
         'admission_contract.reviewed_subject is not the generator commit')
    need('rebind' not in p, 'prospective already carries a rebind block')
    names = p.get('preserved_functions')
    need(isinstance(names, list) and names and all(isinstance(n, str) for n in names) and len(set(names)) == len(names),
         'preserved_functions must be a non-empty list of unique names')
    return recipe


def validate_subject(subject):
    need(isinstance(subject, str) and re.fullmatch(r'[0-9a-f]{40}', subject), 'reviewed subject must be 40 lowercase hex characters')
    need(subject != OLD_SUBJECT, 'reviewed subject must differ from the generator commit')


def substitutions(subject):
    return [
        (f"KEY='{KEY}'\n", ''),
        (f"repo=Path('{WORKBAY_ROOT}')/KEY", f"repo=Path('{SOURCE_ROOT}')/SOURCE"),
        ("python=repo.parent/('.venv-lane-'+KEY)/'bin/python'", "python=repo.parent/(SOURCE+'.venv')/'bin/python'"),
        (f"reviewed_subject='{OLD_SUBJECT}'", f"reviewed_subject='{subject}'"),
    ]


def rebind_text(old, subject):
    subs = substitutions(subject)
    for before, _ in subs:
        found = old.count(before)
        need(found == 1, f'{before!r} must occur exactly once, found {found}')
    new = old
    for before, after in subs:
        new = new.replace(before, after, 1)
    return new, subs


def top_level_value(tree, name):
    hits = [n.value for n in tree.body
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    need(len(hits) == 1, f'top-level {name} must be assigned exactly once, found {len(hits)}')
    return hits[0]


def function_sources(text, name):
    # Decorators and the def, as exact source text, so an edit to either is caught.
    hits = [n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    need(len(hits) == 1, f'function {name} must be defined exactly once, found {len(hits)}')
    node = hits[0]
    return [ast.get_source_segment(text, d) for d in node.decorator_list], ast.get_source_segment(text, node)


def check_recipe(old, new, preserved):
    try:
        tree = ast.parse(new)
    except SyntaxError as e:
        raise Refusal(f'rebound recipe does not parse: {e}')
    for token in FORBIDDEN:
        need(token not in new, f'rebound recipe still contains {token!r}')
    need(new.count(f"SOURCE='{SOURCE}'") == 1, f'SOURCE={SOURCE!r} must occur exactly once')
    source = top_level_value(tree, 'SOURCE')
    need(isinstance(source, ast.Constant) and source.value == SOURCE, 'top-level SOURCE must be the durable source commit')
    need(ast.dump(top_level_value(tree, 'repo')) == REPO_EXPR, 'repo must be exactly Path(<source root>)/SOURCE')
    need(ast.dump(top_level_value(tree, 'python')) == PYTHON_EXPR, "python must be exactly repo.parent/(SOURCE+'.venv')/'bin/python'")
    for name in preserved:
        need(function_sources(old, name) == function_sources(new, name), f'preserved function {name} changed')


def render(p, new, subs, subject):
    remote = new.encode()
    to_sha = sha256(remote)
    doc = dict(
        p,
        executable_recipe=new,
        recipe_sha256=to_sha,
        admission_contract=dict(p['admission_contract'], reviewed_subject=subject),
        rebind=dict(
            from_recipe_sha256=p['recipe_sha256'],
            to_recipe_sha256=to_sha,
            reviewed_subject_from=OLD_SUBJECT,
            reviewed_subject_to=subject,
            source_root=SOURCE_ROOT,
            substitutions=[dict(old=before, new=after) for before, after in subs],
            canon=CANON,
        ),
    )
    return {PROSPECTIVE_NAME: (json.dumps(doc, indent=2) + '\n').encode(), REMOTE_NAME: remote}, to_sha


def regular_bytes(path):
    st = os.lstat(path)
    need(stat.S_ISREG(st.st_mode), f'{path} is not a regular non-symlink file')
    return path.read_bytes()


@contextlib.contextmanager
def writer_lock(out):
    need(not out.exists() or out.is_dir(), f'{out} exists and is not a directory')
    out.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refusal(f'{out} is locked by another writer')
        yield fd
    finally:
        os.close(fd)


def plan_writes(out, files):
    todo = {}
    for name in PUBLISH_ORDER:
        target = out / name
        if os.path.lexists(target):
            need(regular_bytes(target) == files[name], f'{target} exists with different bytes; refusing to overwrite')
        else:
            todo[name] = files[name]
    return todo


def stage(tmp, data):
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, 'wb') as f:
        os.fchmod(f.fileno(), 0o644)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
        st = os.fstat(f.fileno())
    return st.st_dev, st.st_ino


def publish_one(dirfd, out, name, data, linked, temps):
    dest = out / name
    tmp = out / f'.{name}.{uuid.uuid4().hex}.tmp'
    temps.append(tmp)
    identity = stage(tmp, data)
    try:
        os.link(tmp, dest)
    except FileExistsError:
        need(regular_bytes(dest) == data, f'{dest} appeared with different bytes during publication; refusing to overwrite (late conflict)')
    else:
        linked.append((dest, identity))
    os.unlink(tmp)
    os.fsync(dirfd)


def unlink_if_present(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return True


def unlink_if_ours(path, identity):
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if (st.st_dev, st.st_ino) != identity:
        return True
    return unlink_if_present(path)


def rollback(dirfd, linked, temps):
    # Returns the paths that could not be cleared. Preexisting files are never in `linked`, so never touched.
    stuck = []
    for dest, identity in reversed(linked):
        if not unlink_if_ours(dest, identity):
            stuck.append(str(dest))
    for tmp in temps:
        if not unlink_if_present(tmp):
            stuck.append(str(tmp))
    os.fsync(dirfd)
    return stuck


def publish(dirfd, out, todo):
    linked, temps = [], []
    try:
        for name in PUBLISH_ORDER:
            if name in todo:
                publish_one(dirfd, out, name, todo[name], linked, temps)
    except BaseException as cause:
        stuck = rollback(dirfd, linked, temps)
        if stuck:
            raise Refusal(f"rollback incomplete: {', '.join(stuck)}; publication failed: {cause}") from cause
        raise


def run(prospective, subject, out):
    validate_subject(subject)
    p = load_prospective(prospective)
    old = validate_prospective(p)
    new, subs = rebind_text(old, subject)
    check_recipe(old, new, p['preserved_functions'])
    files, to_sha = render(p, new, subs, subject)
    with writer_lock(out) as dirfd:
        todo = plan_writes(out, files)
        publish(dirfd, out, todo)
    return dict(status='REBOUND' if todo else 'ALREADY_REBOUND', recipe_sha256=to_sha, out=str(out))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--prospective', required=True)
    ap.add_argument('--reviewed-subject', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    try:
        result = run(a.prospective, a.reviewed_subject, out)
    except (Refusal, OSError) as e:
        print(json.dumps(dict(status='REFUSED', recipe_sha256=None, out=str(out), reason=str(e))))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
