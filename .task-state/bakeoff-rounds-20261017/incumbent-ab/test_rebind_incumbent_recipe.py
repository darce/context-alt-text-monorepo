"""Tests for rebind_incumbent_recipe: stdlib only, no network, VM or recipe execution."""
import ast
import contextlib
import fcntl
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rebind_incumbent_recipe as rb  # noqa: E402


def load_qwen_runner():
    spec = importlib.util.spec_from_file_location('qwen_runner_under_test', HERE.parent / 'qwen-ab' / 'run_qwen_cohort_operation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


QWEN = load_qwen_runner()
OLD = rb.OLD_SUBJECT
NEW = '0123456789abcdef0123456789abcdef01234567'
KEY = rb.KEY
DURABLE_ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/source'

RECIPE = f"""KEY='{KEY}'
SOURCE='{rb.SOURCE}'
repo=Path('/home/gate/workbay-sandbox')/KEY
python=repo.parent/('.venv-lane-'+KEY)/'bin/python'
reviewed_subject='{OLD}'


def public(x):
    return x + 1


def observe(y):
    return [y, repo, python]
"""

REBOUND = f"""SOURCE='{rb.SOURCE}'
repo=Path('{DURABLE_ROOT}')/SOURCE
python=repo.parent/(SOURCE+'.venv')/'bin/python'
reviewed_subject='{NEW}'


def public(x):
    return x + 1


def observe(y):
    return [y, repo, python]
"""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def top_level(tree, name):
    return next(n.value for n in tree.body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', None) == name)


PIN = sha256(RECIPE.encode())
# Runs the real main() in a child with the production pin patched to the synthetic recipe's digest.
PIN_HARNESS = ('import sys; sys.path.insert(0, sys.argv[1]); import rebind_incumbent_recipe as rb; '
               'rb.SOURCE_RECIPE_SHA256 = sys.argv[2]; sys.exit(rb.main(sys.argv[3:]))')


def cli_subprocess(args, pinned=False):
    if pinned:
        cmd = [sys.executable, '-B', '-c', PIN_HARNESS, str(HERE), PIN, *args]
    else:
        cmd = [sys.executable, '-B', str(HERE / 'rebind_incumbent_recipe.py'), *args]
    return subprocess.run(cmd, capture_output=True, text=True)


class RebindTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def prospective(self, recipe=RECIPE, **over):
        # Pins the module digest to this recipe, as the real pin would be for the stored artifact.
        patch = mock.patch.object(rb, 'SOURCE_RECIPE_SHA256', sha256(recipe.encode()))
        patch.start()
        self.addCleanup(patch.stop)
        p = {
            'schema': rb.SCHEMA,
            'status': rb.STATUS,
            'execution_started': False,
            'executable_recipe': recipe,
            'recipe_sha256': sha256(recipe.encode()),
            'admission_contract': {'reviewed_subject': OLD, 'gate': 'independent'},
            'preserved_functions': ['public', 'observe'],
        }
        p.update(over)
        return p

    def write(self, name, obj):
        path = self.dir / name
        path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding='utf-8')
        return str(path)

    def cli(self, prospective, subject=NEW, out=None):
        out = out or str(self.dir / 'out')
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = rb.main(['--prospective', prospective, '--reviewed-subject', subject, '--out', out])
        return rc, json.loads(buf.getvalue())

    def assertRefused(self, p, subject=NEW, contains=None):
        out = self.dir / 'out'
        rc, res = self.cli(self.write('in.json', p), subject=subject, out=str(out))
        self.assertEqual(rc, 3)
        self.assertEqual(res['status'], 'REFUSED')
        if contains:
            self.assertIn(contains, res['reason'])
        self.assertFalse(out.exists())
        return res

    def test_pinned_constants_match_brief(self):
        self.assertEqual(rb.SOURCE_RECIPE_SHA256, '603f1a9b1e65f5c1ade9e3753d7afad5099ece8e872ab3bb2cac167a7bdac3f5')
        self.assertEqual(rb.SOURCE, 'ab94e904ca25e2e031ad241f2600aa0406201c15')
        self.assertEqual(rb.SOURCE_ROOT, DURABLE_ROOT)

    def test_happy_path_writes_both_files_with_exact_recipe_and_rebind_block(self):
        p = self.prospective()
        rc, res = self.cli(self.write('in.json', p))
        self.assertEqual(rc, 0)
        self.assertEqual(res['status'], 'REBOUND')
        out = self.dir / 'out'
        remote = (out / rb.REMOTE_NAME).read_bytes()
        doc = json.loads((out / rb.PROSPECTIVE_NAME).read_text(encoding='utf-8'))
        self.assertEqual(remote.decode(), REBOUND)
        self.assertEqual(res['recipe_sha256'], sha256(remote))
        self.assertEqual(doc['executable_recipe'], REBOUND)
        self.assertEqual(doc['recipe_sha256'], sha256(remote))
        self.assertEqual(doc['admission_contract'], {'reviewed_subject': NEW, 'gate': 'independent'})
        self.assertEqual((doc['schema'], doc['status'], doc['execution_started']), (rb.SCHEMA, rb.STATUS, False))
        self.assertEqual(doc['preserved_functions'], ['public', 'observe'])
        self.assertEqual(doc['rebind'], {
            'from_recipe_sha256': p['recipe_sha256'],
            'to_recipe_sha256': sha256(remote),
            'reviewed_subject_from': OLD,
            'reviewed_subject_to': NEW,
            'source_root': DURABLE_ROOT,
            'substitutions': [
                {'old': f"KEY='{KEY}'\n", 'new': ''},
                {'old': "repo=Path('/home/gate/workbay-sandbox')/KEY", 'new': f"repo=Path('{DURABLE_ROOT}')/SOURCE"},
                {'old': "python=repo.parent/('.venv-lane-'+KEY)/'bin/python'", 'new': "python=repo.parent/(SOURCE+'.venv')/'bin/python'"},
                {'old': f"reviewed_subject='{OLD}'", 'new': f"reviewed_subject='{NEW}'"},
            ],
            'canon': 'v0.26.2 RLSE-21 FLOW-01',
        })
        tree = ast.parse(remote.decode())
        self.assertEqual(ast.dump(top_level(tree, 'repo')), QWEN.REPO_EXPR)
        self.assertEqual(ast.dump(top_level(tree, 'python')), QWEN.PYTHON_EXPR)
        self.assertEqual(ast.dump(top_level(tree, 'repo')), rb.REPO_EXPR)

    def test_wrapper_and_bare_inputs_give_identical_outputs(self):
        p = self.prospective()
        rc1, _ = self.cli(self.write('bare.json', p), out=str(self.dir / 'a'))
        rc2, _ = self.cli(self.write('wrap.json', {'prospective': p, 'source': 'x'}), out=str(self.dir / 'b'))
        self.assertEqual((rc1, rc2), (0, 0))
        for name in (rb.PROSPECTIVE_NAME, rb.REMOTE_NAME):
            self.assertEqual((self.dir / 'a' / name).read_bytes(), (self.dir / 'b' / name).read_bytes())

    def test_each_old_missing_refuses(self):
        cases = {
            'KEY line': RECIPE.replace(f"KEY='{KEY}'\n", ''),
            'repo line': RECIPE.replace("repo=Path('/home/gate/workbay-sandbox')/KEY", "repo=Path('/tmp/elsewhere')/KEY"),
            'python line': RECIPE.replace("python=repo.parent/('.venv-lane-'+KEY)/'bin/python'", "python=repo.parent/'bin/python'"),
            'subject': RECIPE.replace(f"reviewed_subject='{OLD}'", "reviewed_subject=''"),
        }
        for label, recipe in cases.items():
            with self.subTest(label):
                self.assertRefused(self.prospective(recipe), contains='exactly once, found 0')

    def test_each_old_duplicated_refuses(self):
        dups = {
            'KEY line': f"KEY='{KEY}'\n",
            'repo line': "repo=Path('/home/gate/workbay-sandbox')/KEY\n",
            'python line': "python=repo.parent/('.venv-lane-'+KEY)/'bin/python'\n",
            'subject': f"reviewed_subject='{OLD}'\n",
        }
        for label, line in dups.items():
            with self.subTest(label):
                self.assertRefused(self.prospective(RECIPE + line), contains='exactly once, found 2')

    def test_wrong_pin_refuses(self):
        p = self.prospective()
        with mock.patch.object(rb, 'SOURCE_RECIPE_SHA256', '1' * 64):
            self.assertRefused(p, contains='not the pinned incumbent recipe')

    def test_recipe_sha_mismatch_refuses(self):
        self.assertRefused(self.prospective(recipe_sha256='0' * 64), contains='does not match')
        p = self.prospective()
        p['executable_recipe'] = RECIPE + '# edited after the digest was taken\n'
        self.assertRefused(p, contains='does not match')

    def test_bad_input_fields_refuse(self):
        cases = {
            'schema': dict(schema='other/v1', contains='schema'),
            'status': dict(status='EXECUTED', contains='status'),
            'execution_started': dict(execution_started=0, contains='execution_started'),
            'contract subject': dict(admission_contract={'reviewed_subject': NEW}, contains='admission_contract'),
            'already rebound': dict(rebind={'canon': 'x'}, contains='already carries'),
            'no preserved list': dict(preserved_functions=[], contains='preserved_functions'),
            'absent preserved function': dict(preserved_functions=['public', 'absent'], contains='absent'),
        }
        for label, over in cases.items():
            with self.subTest(label):
                contains = over.pop('contains')
                self.assertRefused(self.prospective(**over), contains=contains)

    def test_bad_subject_refuses(self):
        p = self.prospective()
        for subject in ['a' * 39, NEW + 'a', NEW.upper(), 'g' * 40, '', OLD]:
            with self.subTest(subject=subject):
                self.assertRefused(p, subject=subject)

    def test_preserved_function_edited_refuses(self):
        recipe = RECIPE.replace(f"reviewed_subject='{OLD}'\n", '').replace(
            'def observe(y):\n', f"def observe(y):\n    reviewed_subject='{OLD}'\n")
        self.assertRefused(self.prospective(recipe), contains='preserved function observe changed')

    def test_residual_forbidden_text_refuses(self):
        for token in ['KEY', 'workbay-sandbox', 'venv-lane', 'c8ddf610']:
            with self.subTest(token=token):
                recipe = RECIPE.replace('def public(x):\n', f'# {token}\ndef public(x):\n')
                self.assertRefused(self.prospective(recipe), contains=token)

    def test_repo_and_python_must_match_qwen_runner_constants(self):
        repo = RECIPE.replace("repo=Path('/home/gate/workbay-sandbox')/KEY", "repo=Path('/home/gate/workbay-sandbox')/KEY/'extra'")
        self.assertRefused(self.prospective(repo), contains='repo must be exactly')
        python = RECIPE.replace("'bin/python'\n", "'bin/python'/'x'\n")
        self.assertRefused(self.prospective(python), contains='python must be exactly')

    def test_rerun_identical_is_noop(self):
        path = self.write('in.json', self.prospective())
        rc1, first = self.cli(path)
        out = self.dir / 'out'
        before = {n: (out / n).read_bytes() for n in (rb.PROSPECTIVE_NAME, rb.REMOTE_NAME)}
        rc2, second = self.cli(path)
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual(second['status'], 'ALREADY_REBOUND')
        self.assertEqual(second['recipe_sha256'], first['recipe_sha256'])
        self.assertEqual(before, {n: (out / n).read_bytes() for n in before})

    def test_existing_different_target_refuses_and_changes_nothing(self):
        out = self.dir / 'out'
        out.mkdir()
        (out / rb.REMOTE_NAME).write_bytes(b'stale\n')
        rc, res = self.cli(self.write('in.json', self.prospective()), out=str(out))
        self.assertEqual(rc, 3)
        self.assertIn('different bytes', res['reason'])
        self.assertEqual((out / rb.REMOTE_NAME).read_bytes(), b'stale\n')
        self.assertEqual(sorted(p.name for p in out.iterdir()), [rb.REMOTE_NAME])

    def test_cli_entry_point_refuses_with_exit_3_and_writes_nothing(self):
        # The subprocess does not see the in-process pin, so the real digest pin refuses the synthetic recipe.
        out = self.dir / 'out'
        path = self.write('in.json', self.prospective())
        r = subprocess.run([sys.executable, '-B', str(HERE / 'rebind_incumbent_recipe.py'), '--prospective', path,
                            '--reviewed-subject', NEW, '--out', str(out)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'], 'REFUSED')
        self.assertFalse(out.exists())

    def publish_names(self, out):
        return sorted(p.name for p in out.iterdir())

    def one_refusal_line(self, r):
        self.assertEqual(r.returncode, 3, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1, r.stdout)
        res = json.loads(lines[0])
        self.assertEqual(res['status'], 'REFUSED')
        return res

    def test_fresh_publish_links_remote_then_prospective_and_leaves_only_outputs(self):
        real_link = os.link
        linked = []

        def recording_link(src, dst, *args, **kwargs):
            linked.append(Path(dst).name)
            return real_link(src, dst, *args, **kwargs)

        out = self.dir / 'out'
        with mock.patch('os.link', side_effect=recording_link):
            rc, res = self.cli(self.write('in.json', self.prospective()), out=str(out))
        self.assertEqual((rc, res['status']), (0, 'REBOUND'))
        self.assertEqual(linked, [rb.REMOTE_NAME, rb.PROSPECTIVE_NAME])
        self.assertEqual(self.publish_names(out), sorted([rb.PROSPECTIVE_NAME, rb.REMOTE_NAME]))

    def test_second_publication_failure_on_fresh_out_leaves_no_pair_and_no_temp(self):
        real_link = os.link
        attempts = []

        def flaky_link(src, dst, *args, **kwargs):
            attempts.append(Path(dst).name)
            if len(attempts) == 2:
                raise PermissionError(13, 'injected second link failure')
            return real_link(src, dst, *args, **kwargs)

        path = self.write('in.json', self.prospective())
        out = self.dir / 'out'
        with mock.patch('os.link', side_effect=flaky_link):
            rc, res = self.cli(path, out=str(out))
        self.assertEqual((rc, res['status']), (3, 'REFUSED'))
        self.assertIn('injected second link failure', res['reason'])
        self.assertEqual(attempts, [rb.REMOTE_NAME, rb.PROSPECTIVE_NAME])
        self.assertEqual(self.publish_names(out), [])

    def test_second_publication_failure_keeps_identical_preexisting_remote(self):
        path = self.write('in.json', self.prospective())
        ref = self.dir / 'ref'
        self.assertEqual(self.cli(path, out=str(ref))[0], 0)
        out = self.dir / 'out'
        out.mkdir()
        remote = out / rb.REMOTE_NAME
        remote.write_bytes((ref / rb.REMOTE_NAME).read_bytes())
        inode = remote.stat().st_ino
        real_link = os.link

        def failing_prospective_link(src, dst, *args, **kwargs):
            if Path(dst).name == rb.PROSPECTIVE_NAME:
                raise PermissionError(13, 'injected prospective link failure')
            return real_link(src, dst, *args, **kwargs)

        with mock.patch('os.link', side_effect=failing_prospective_link):
            rc, res = self.cli(path, out=str(out))
        self.assertEqual((rc, res['status']), (3, 'REFUSED'))
        self.assertIn('injected prospective link failure', res['reason'])
        self.assertEqual(remote.read_bytes(), (ref / rb.REMOTE_NAME).read_bytes())
        self.assertEqual(remote.stat().st_ino, inode)
        self.assertEqual(self.publish_names(out), [rb.REMOTE_NAME])

    def test_late_conflict_refuses_keeps_competitor_bytes_and_unlinks_own_remote(self):
        real_link = os.link
        competitor = b'competing writer\n'

        def racing_link(src, dst, *args, **kwargs):
            if Path(dst).name == rb.PROSPECTIVE_NAME:
                Path(dst).write_bytes(competitor)
            return real_link(src, dst, *args, **kwargs)

        path = self.write('in.json', self.prospective())
        out = self.dir / 'out'
        with mock.patch('os.link', side_effect=racing_link):
            rc, res = self.cli(path, out=str(out))
        self.assertEqual((rc, res['status']), (3, 'REFUSED'))
        self.assertIn('different bytes', res['reason'])
        self.assertEqual((out / rb.PROSPECTIVE_NAME).read_bytes(), competitor)
        self.assertEqual(self.publish_names(out), [rb.PROSPECTIVE_NAME])

    def test_rollback_failure_names_residual_path(self):
        real_link, real_unlink = os.link, os.unlink

        def failing_prospective_link(src, dst, *args, **kwargs):
            if Path(dst).name == rb.PROSPECTIVE_NAME:
                raise PermissionError(13, 'injected prospective link failure')
            return real_link(src, dst, *args, **kwargs)

        def stuck_unlink(path, *args, **kwargs):
            if Path(path).name == rb.REMOTE_NAME:
                raise PermissionError(13, 'injected unlink failure')
            return real_unlink(path, *args, **kwargs)

        path = self.write('in.json', self.prospective())
        out = self.dir / 'out'
        with mock.patch('os.link', side_effect=failing_prospective_link), mock.patch('os.unlink', side_effect=stuck_unlink):
            rc, res = self.cli(path, out=str(out))
        self.assertEqual((rc, res['status']), (3, 'REFUSED'))
        self.assertIn(f'rollback incomplete: {out / rb.REMOTE_NAME}', res['reason'])
        self.assertEqual(self.publish_names(out), [rb.REMOTE_NAME])

    def test_identical_rerun_keeps_inodes_and_outputs(self):
        path = self.write('in.json', self.prospective())
        self.assertEqual(self.cli(path)[0], 0)
        out = self.dir / 'out'
        names = (rb.PROSPECTIVE_NAME, rb.REMOTE_NAME)
        inodes = {n: (out / n).stat().st_ino for n in names}
        rc, res = self.cli(path)
        self.assertEqual((rc, res['status']), (0, 'ALREADY_REBOUND'))
        self.assertEqual(inodes, {n: (out / n).stat().st_ino for n in names})
        self.assertEqual(self.publish_names(out), sorted(names))

    def test_symlink_destination_refuses_and_is_left_alone(self):
        out = self.dir / 'out'
        out.mkdir()
        target = self.dir / 'elsewhere.json'
        target.write_bytes(b'x')
        (out / rb.PROSPECTIVE_NAME).symlink_to(target)
        rc, res = self.cli(self.write('in.json', self.prospective()), out=str(out))
        self.assertEqual((rc, res['status']), (3, 'REFUSED'))
        self.assertIn('not a regular non-symlink file', res['reason'])
        self.assertTrue((out / rb.PROSPECTIVE_NAME).is_symlink())
        self.assertEqual(target.read_bytes(), b'x')
        self.assertEqual(self.publish_names(out), [rb.PROSPECTIVE_NAME])

    def test_busy_out_dir_refuses_from_subprocess_and_writes_nothing(self):
        out = self.dir / 'out'
        out.mkdir()
        holder = os.open(out, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, holder)
        fcntl.flock(holder, fcntl.LOCK_EX)
        path = self.write('in.json', self.prospective())
        res = self.one_refusal_line(cli_subprocess(['--prospective', path, '--reviewed-subject', NEW, '--out', str(out)], pinned=True))
        self.assertIn('locked by another writer', res['reason'])
        self.assertEqual(self.publish_names(out), [])

    def test_unpaired_surrogate_in_recipe_refuses_from_subprocess_with_one_json_line(self):
        p = self.prospective()
        p['executable_recipe'] = RECIPE + '# \ud800\n'
        path = self.write('in.json', p)
        out = self.dir / 'out'
        res = self.one_refusal_line(cli_subprocess(['--prospective', path, '--reviewed-subject', NEW, '--out', str(out)], pinned=True))
        self.assertIn('UTF-8', res['reason'])
        self.assertFalse(out.exists())

    def test_unreadable_or_invalid_json_input_refuses_with_one_json_line(self):
        out = self.dir / 'out'
        for label, path in [('invalid JSON', self.write('bad.json', '{not json')),
                            ('missing file', str(self.dir / 'absent.json'))]:
            with self.subTest(label):
                rc, res = self.cli(path, out=str(out))
                self.assertEqual((rc, res['status']), (3, 'REFUSED'))
                self.assertFalse(out.exists())

    def test_output_parent_is_regular_file_refuses_from_subprocess_and_leaves_input(self):
        blocker = self.dir / 'blocker'
        blocker.write_bytes(b'not a directory\n')
        path = self.write('in.json', self.prospective())
        before = Path(path).read_bytes()
        res = self.one_refusal_line(cli_subprocess(['--prospective', path, '--reviewed-subject', NEW, '--out', str(blocker / 'out')], pinned=True))
        self.assertIn('Not a directory', res['reason'])
        self.assertEqual(Path(path).read_bytes(), before)
        self.assertEqual(blocker.read_bytes(), b'not a directory\n')


if __name__ == '__main__':
    unittest.main()
