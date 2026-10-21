"""Rebind the gated incumbent pilot recipe to the durable source root (BAKEOFF-INC-REBIND-20261020, RLSE-21).

Promotes the stored, already-gated prospective artifact with exactly four substitutions. No generator is restored.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
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
    digest = sha256(recipe.encode())
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


def plan_writes(out, files):
    need(not out.exists() or out.is_dir(), f'{out} exists and is not a directory')
    todo = {}
    for name, data in files.items():
        target = out / name
        if os.path.lexists(target):
            need(target.is_file() and target.read_bytes() == data, f'{target} exists with different bytes; refusing to overwrite')
        else:
            todo[name] = data
    return todo


def commit_writes(out, todo):
    if not todo:
        return
    out.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for name, data in todo.items():
            fd, tmp = tempfile.mkstemp(dir=out, prefix=f'.{name}.')
            staged.append((tmp, out / name))
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp, 0o644)
        for tmp, target in staged:
            os.replace(tmp, target)
    finally:
        for tmp, _ in staged:
            if os.path.exists(tmp):
                os.unlink(tmp)


def run(prospective, subject, out):
    validate_subject(subject)
    p = load_prospective(prospective)
    old = validate_prospective(p)
    new, subs = rebind_text(old, subject)
    check_recipe(old, new, p['preserved_functions'])
    files, to_sha = render(p, new, subs, subject)
    todo = plan_writes(out, files)
    commit_writes(out, todo)
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
    except Refusal as e:
        print(json.dumps(dict(status='REFUSED', recipe_sha256=None, out=str(out), reason=str(e))))
        return 3
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
