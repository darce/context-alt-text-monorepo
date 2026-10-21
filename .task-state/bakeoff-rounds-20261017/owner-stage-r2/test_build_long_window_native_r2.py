import ast
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

import build_long_window_native_r2 as gen

SOURCE = 'a' * 40
PRED_OP = 'a9e13611-f042-44e4-8aa4-2e81e6d19597'
OTHER_OP = str(uuid.UUID(int=2))
WINDOW = '/tmp/qwen-owner-window.rcqmefq9'
WINDOW_ID = '223eb2de-b63a-4b19-a31e-a34d07a8e187'
R3_STAGE = '/root/owner-stop-contract-r3/procedure'
SCHEMA = 'acx-owner-procedure-predecessor/v1'
PROCEDURE = Path(__file__).resolve().parents[1] / 'qualifications' / 'owner-resume-start-r4'
PROCEDURE_DIR = gen.PROCEDURE_DIR
FORBIDDEN = ('checkpoint', 'reconcile', 'rmtree', 'unlink', 'remove')
STDLIB = {'base64', 'hashlib', 'importlib', 'json', 'os', 'pathlib', 'stat', 'sys', 'time', 'uuid'}
EXPECTED_CONSTANTS = dict(
    STAGE='/root/bakeoff-owner-long-window-20261020-cd399f1f0d55/procedure',
    OLD_STAGE=R3_STAGE,
    CURRENT_STAGE='/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure',
    WINDOW=WINDOW,
    WINDOW_ID=WINDOW_ID,
    EXPECT_OPS=24,
    PRED_OP=PRED_OP,
)
MUTATED_FIELDS = dict(
    schema='acx-owner-procedure-predecessor/v2',
    window_id=str(uuid.UUID(int=1)),
    window_path='/tmp/other-window',
    procedure='/root/other-stage/procedure',
    manifest_sha256='0' * 64,
    owner_window_sha256='1' * 64,
    owner_custody_sha256='2' * 64,
)


def real_tree():
    return {name: (PROCEDURE / name).read_bytes() for name in gen.EXPECTED_NAMES}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def program_constants(program):
    values = {}
    for node in ast.parse(program).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return values


def program_namespace(program):
    """Exec the generated program without its final run() call, so its helpers can be tested."""
    if not program.endswith('\nrun()\n'):
        raise AssertionError('generated program must end with run()')
    namespace = {'__name__': 'generated_program_under_test'}
    exec(compile(program[:-len('run()\n')], 'generated-program', 'exec'), namespace)
    namespace['ROOT_UID'] = os.geteuid()
    return namespace


def write_sealed(path, value):
    raw = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


def secure_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def write_stage(path, files):
    secure_dir(path)
    for name, raw in files.items():
        write_sealed(path / name, raw)
    return path


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def generate(self, tree=None, expect_ops=24, source=SOURCE):
        return gen.build(source, expect_ops, Path(self.tmp.name), PRED_OP,
                         load_tree=lambda _: dict(real_tree() if tree is None else tree))

    def test_happy_path_writes_the_config_and_the_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, program_path = gen.build(SOURCE, 24, Path(tmp), PRED_OP,
                                                  load_tree=lambda _: real_tree())
            config = json.loads(config_path.read_bytes())
            self.assertEqual(config, dict(
                name='BAKEOFF-LONG-WINDOW-NATIVE-R2', owner='Bakeoff_LongLive',
                unit='workbay-bakeoff-long-window-native-r2-20261020.scope', model=None, cpu=0.5,
                memory=2147483648, forecast=1073741824, source=SOURCE, timeout=120,
                role='qualified_root_bounded_view_stage_no_window_mutation',
                program=str(program_path.absolute())))
            self.assertTrue(program_path.is_absolute())
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             sorted([gen.CONFIG_NAME, gen.PROGRAM_NAME]))

    def test_program_parses_and_embeds_exactly_the_eight_files(self):
        _, program_path = self.generate()
        program = program_path.read_text()
        embedded = program_constants(program)['v']['files']
        self.assertEqual(set(embedded), gen.EXPECTED_NAMES)
        self.assertEqual(len(embedded), 8)
        for name, raw in real_tree().items():
            self.assertEqual(base64.b64decode(embedded[name], validate=True), raw, name)
        self.assertEqual(sha(base64.b64decode(embedded['approved-scripts.json'])), gen.MANIFEST_SHA256)

    def test_program_sets_the_stage_and_window_constants_exactly(self):
        _, program_path = self.generate()
        constants = program_constants(program_path.read_text())
        for name, value in EXPECTED_CONSTANTS.items():
            with self.subTest(name=name):
                self.assertEqual(constants[name], value)
        self.assertEqual(constants['SOURCE'], SOURCE)
        self.assertEqual(constants['MANIFEST_SHA256'], gen.MANIFEST_SHA256)
        self.assertEqual(constants['OLD_MANIFEST_SHA256'], '991aa72e923562bec93659190e87f9d223514da3073b424df5d36a60f1e77406')
        self.assertEqual(constants['CURRENT_MANIFEST_SHA256'], '45c86daf3bc312eea23ab1382965b56dcbc1c97dd1c82070decc6ee617d3c5ca')
        self.assertEqual(constants['OWNER_WINDOW_SHA256'], gen.OWNER_WINDOW_SHA256)
        self.assertEqual(constants['OWNER_CUSTODY_SHA256'], gen.OWNER_CUSTODY_SHA256)

    def test_program_has_no_mutating_calls(self):
        _, program_path = self.generate()
        program = program_path.read_text()
        v_line = next(line for line in program.splitlines() if line.startswith('v={'))
        text = program.replace(v_line, '')
        for word in FORBIDDEN:
            with self.subTest(word=word):
                self.assertNotIn(word, text)
        for node in ast.walk(ast.parse(program)):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, FORBIDDEN)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, FORBIDDEN)
        imports = {alias.name.split('.')[0] for node in ast.walk(ast.parse(program))
                   if isinstance(node, ast.Import) for alias in node.names}
        imports |= {node.module.split('.')[0] for node in ast.walk(ast.parse(program))
                    if isinstance(node, ast.ImportFrom)}
        self.assertLessEqual(imports, STDLIB)
        self.assertIn('run()', program)

    def test_readiness_runs_before_the_stage_is_created(self):
        program = gen.render_program(SOURCE, 24, PRED_OP, real_tree())
        run = next(node for node in ast.parse(program).body
                   if isinstance(node, ast.FunctionDef) and node.name == 'run')
        first_line = {}
        for node in ast.walk(run):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                first_line[node.func.id] = min(first_line.get(node.func.id, node.lineno), node.lineno)
        self.assertLess(first_line['readiness_check'], first_line['create_stage'])
        self.assertLess(first_line['readiness_check'], first_line['predecessor_proof'])

    def test_wrong_manifest_digest_refuses(self):
        tree = real_tree()
        tree['approved-scripts.json'] = tree['approved-scripts.json'] + b' '
        with self.assertRaises(gen.Refused):
            self.generate(tree=tree)

    def test_pin_mismatch_refuses(self):
        tree = real_tree()
        tree['owner-custody.py'] = tree['owner-custody.py'] + b'#\n'
        with self.assertRaisesRegex(gen.Refused, 'pin mismatch: owner-custody.py'):
            self.generate(tree=tree)

    def test_extra_file_refuses(self):
        tree = dict(real_tree(), **{'extra.py': b'print(1)\n'})
        with self.assertRaisesRegex(gen.Refused, 'extra'):
            self.generate(tree=tree)

    def test_missing_file_refuses(self):
        tree = real_tree()
        del tree['root-flow.sh']
        with self.assertRaisesRegex(gen.Refused, 'missing'):
            self.generate(tree=tree)

    def test_expect_ops_missing_refuses_at_the_cli(self):
        with self.assertRaises(SystemExit) as caught:
            gen.main(['--source', SOURCE, '--predecessor-op', PRED_OP, '--out-dir', self.tmp.name])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_predecessor_op_required_at_the_cli(self):
        with self.assertRaises(SystemExit) as caught:
            gen.main(['--source', SOURCE, '--expect-ops', '24', '--out-dir', self.tmp.name])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_predecessor_op_must_be_a_canonical_uuid(self):
        for predecessor in (PRED_OP.upper(), PRED_OP.replace('-', ''), 'not-a-uuid', ''):
            with self.subTest(predecessor=predecessor), self.assertRaises(gen.Refused):
                gen.build(SOURCE, 24, Path(self.tmp.name), predecessor, load_tree=lambda _: real_tree())

    def test_expect_ops_must_be_positive(self):
        for expect_ops in (0, -1):
            with self.subTest(expect_ops=expect_ops), self.assertRaises(gen.Refused):
                self.generate(expect_ops=expect_ops)

    def test_source_must_be_a_full_commit(self):
        for source in ('abc', 'G' * 40, 'a' * 39):
            with self.subTest(source=source), self.assertRaises(gen.Refused):
                self.generate(source=source)

    def test_existing_config_refuses_without_writing_the_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / gen.CONFIG_NAME).write_text('{}\n')
            with self.assertRaisesRegex(gen.Refused, 'no overwrite'):
                gen.build(SOURCE, 24, out, PRED_OP, load_tree=lambda _: real_tree())
            self.assertEqual((out / gen.CONFIG_NAME).read_text(), '{}\n')
            self.assertFalse((out / gen.PROGRAM_NAME).exists())

    def test_existing_program_refuses_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / gen.PROGRAM_NAME).write_text('original\n')
            with self.assertRaisesRegex(gen.Refused, 'no overwrite'):
                gen.build(SOURCE, 24, out, PRED_OP, load_tree=lambda _: real_tree())
            self.assertEqual((out / gen.PROGRAM_NAME).read_text(), 'original\n')
            self.assertFalse((out / gen.CONFIG_NAME).exists())


def unrelated_entries(proc):
    (proc / 'ROOT-HANDOFF.md').write_text('handoff\n')
    (proc / 'checkpoint_fixture_plan.py').write_text('print(1)\n')
    (proc / 'test_extra.py').write_text('def test_extra():\n    pass\n')
    os.chmod(proc / 'test_extra.py', 0o755)
    (proc / 'evidence' / 'baseline').mkdir(parents=True)
    (proc / 'evidence' / 'baseline' / 'x.py').write_text('x = 1\n')
    (proc / 'reviews').mkdir()
    (proc / 'reviews' / 'R.md').write_text('review\n')
    os.symlink('ROOT-HANDOFF.md', proc / 'alias.md')


def missing_root_flow(proc):
    unrelated_entries(proc)
    (proc / 'root-flow.sh').unlink()


def root_flow_as_subdir(proc):
    unrelated_entries(proc)
    (proc / 'root-flow.sh').unlink()
    (proc / 'root-flow.sh').mkdir()
    (proc / 'root-flow.sh' / 'inner').write_text('#!/bin/sh\n')


def root_flow_as_symlink(proc):
    unrelated_entries(proc)
    (proc / 'root-flow.sh').unlink()
    os.symlink('owner-window.py', proc / 'root-flow.sh')


def root_flow_as_executable(proc):
    unrelated_entries(proc)
    os.chmod(proc / 'root-flow.sh', 0o755)


class GitLoaderTests(unittest.TestCase):
    """Real git repositories: the unmocked loader must select the eight pinned blobs only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        git(self.tmp.name, 'init', '-q', str(self.repo))

    def commit(self, populate):
        proc = self.repo / PROCEDURE_DIR
        proc.mkdir(parents=True)
        for name, raw in real_tree().items():
            (proc / name).write_bytes(raw)
        populate(proc)
        git(self.repo, 'add', '-A')
        git(self.repo, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'procedure')
        return git(self.repo, 'rev-parse', 'HEAD').strip()

    def assert_refuses(self, populate, pattern):
        source = self.commit(populate)
        with contextlib.chdir(self.repo), self.assertRaisesRegex(gen.Refused, pattern):
            gen.git_tree(source)

    def test_green_returns_exactly_the_eight_pinned_files_and_verifies(self):
        source = self.commit(unrelated_entries)
        with contextlib.chdir(self.repo):
            tree = gen.git_tree(source)
        self.assertEqual(tree, real_tree())
        self.assertEqual(gen.verify_tree(tree), real_tree())

    def test_build_with_the_real_loader_writes_the_program(self):
        source = self.commit(unrelated_entries)
        out = Path(self.tmp.name) / 'out'
        with contextlib.chdir(self.repo):
            config_path, program_path = gen.build(source, 24, out, PRED_OP)
        self.assertEqual(json.loads(config_path.read_bytes())['source'], source)
        embedded = program_constants(program_path.read_text())['v']['files']
        self.assertEqual({name: base64.b64decode(raw) for name, raw in embedded.items()}, real_tree())

    def test_pinned_name_missing_refuses(self):
        self.assert_refuses(missing_root_flow, 'missing procedure entry: root-flow.sh')

    def test_pinned_name_committed_as_subdir_refuses(self):
        self.assert_refuses(root_flow_as_subdir, 'non-regular procedure entry: root-flow.sh')

    def test_pinned_name_committed_as_symlink_refuses(self):
        self.assert_refuses(root_flow_as_symlink, 'non-regular procedure entry: root-flow.sh')

    def test_pinned_name_committed_as_executable_refuses(self):
        self.assert_refuses(root_flow_as_executable, 'non-regular procedure entry: root-flow.sh')


class BridgedReceiptTests(unittest.TestCase):
    """ORG-02: the bridged CURRENT_STAGE is exact nine with a read-only receipt; every other stage is exact eight."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ns = program_namespace(gen.render_program(SOURCE, 24, PRED_OP, real_tree()))
        self.r3 = write_stage(self.root / 'r3', real_tree())
        self.ns['OLD_STAGE'] = str(self.r3)
        self.old = self.ns['verify_procedure'](str(self.r3), gen.MANIFEST_SHA256)
        self.window = dict(id=WINDOW_ID, path=WINDOW, procedure=str(self.r3))
        self.fields = dict(schema=SCHEMA, window_id=WINDOW_ID, window_path=WINDOW, procedure=str(self.r3),
                           manifest_sha256=self.old['manifest_sha256'],
                           owner_window_sha256=self.old['files']['owner-window.py'],
                           owner_custody_sha256=self.old['files']['owner-custody.py'])

    def receipt(self, fields=None):
        return (json.dumps(self.fields if fields is None else fields, sort_keys=True) + '\n').encode()

    def nine_file_stage(self, name, receipt=None):
        files = dict(real_tree(), **{'procedure-predecessor.json': self.receipt() if receipt is None else receipt})
        return write_stage(self.root / name, files)

    def test_valid_nine_file_retained_stage_passes(self):
        stage = self.nine_file_stage('current')
        result = self.ns['verify_procedure'](str(stage), gen.MANIFEST_SHA256, bridged=(self.window, self.old))
        self.assertEqual(sorted(os.listdir(stage)), sorted(gen.EXPECTED_NAMES | {'procedure-predecessor.json'}))
        self.assertEqual(result['manifest_sha256'], gen.MANIFEST_SHA256)
        self.assertEqual(self.ns['check_bridged_receipt'](self.receipt(), self.window, self.old), self.fields)

    def test_receipt_missing_refuses_at_eight_files(self):
        stage = write_stage(self.root / 'missing', real_tree())
        with self.assertRaisesRegex(RuntimeError, 'procedure inventory mismatch'):
            self.ns['verify_procedure'](str(stage), gen.MANIFEST_SHA256, bridged=(self.window, self.old))

    def test_receipt_with_one_field_changed_refuses_once_per_field(self):
        for field, value in MUTATED_FIELDS.items():
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'predecessor receipt'):
                self.ns['check_bridged_receipt'](self.receipt(dict(self.fields, **{field: value})), self.window, self.old)

    def test_receipt_with_an_extra_key_refuses(self):
        with self.assertRaisesRegex(RuntimeError, 'bad predecessor receipt schema'):
            self.ns['check_bridged_receipt'](self.receipt(dict(self.fields, extra='x')), self.window, self.old)

    def test_tenth_file_refuses(self):
        stage = self.nine_file_stage('tenth')
        write_sealed(stage / 'extra.txt', b'extra\n')
        with self.assertRaisesRegex(RuntimeError, 'procedure inventory mismatch'):
            self.ns['verify_procedure'](str(stage), gen.MANIFEST_SHA256, bridged=(self.window, self.old))

    def test_receipt_must_be_exactly_one_json_object_and_newline(self):
        body = self.receipt()[:-1]
        for name, raw in (('no newline', body), ('two newlines', body + b'\n\n'),
                          ('trailing garbage', body + b'x\n'), ('not json', b'nope\n')):
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                self.ns['check_bridged_receipt'](raw, self.window, self.old)

    def test_pre_proof_stage_and_r3_stay_exact_eight(self):
        stage = self.nine_file_stage('pre-proof')
        with self.assertRaisesRegex(RuntimeError, 'procedure inventory mismatch'):
            self.ns['verify_procedure'](str(stage), gen.MANIFEST_SHA256)

    def test_inventory_predicate(self):
        inventory_ok = self.ns['inventory_ok']
        nine = gen.EXPECTED_NAMES | {'procedure-predecessor.json'}
        self.assertTrue(inventory_ok(set(gen.EXPECTED_NAMES), False))
        self.assertTrue(inventory_ok(nine, True))
        self.assertFalse(inventory_ok(set(gen.EXPECTED_NAMES), True))
        self.assertFalse(inventory_ok(nine, False))
        self.assertFalse(inventory_ok(nine | {'extra'}, True))
        self.assertFalse(inventory_ok((set(gen.EXPECTED_NAMES) - {'root-flow.sh'}) | {'procedure-predecessor.json'}, True))


class ReadinessTests(unittest.TestCase):
    """ORG-03: readiness uses the real merged custody functions over temporary state."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ns = program_namespace(gen.render_program(SOURCE, 24, PRED_OP, real_tree()))
        copy = secure_dir(self.root / 'qualified-source')
        write_sealed(copy / 'owner-custody.py', (PROCEDURE / 'owner-custody.py').read_bytes())
        self.custody = self.ns['load_custody'](str(copy / 'owner-custody.py'))
        self.window = secure_dir(self.root / 'window')
        write_sealed(self.window / 'window.json', dict(id=WINDOW_ID, path=str(self.window), procedure=R3_STAGE))
        secure_dir(self.window / 'ops')
        self.store = secure_dir(self.root / 'store')
        for env in self.custody.ENVS:
            write_sealed(secure_dir(self.root / 'runtime' / env) / 'describe-load.json', {})
        self.paths = self.custody.Paths(str(self.root / 'runtime'), str(self.store), str(self.root / 'lifecycle.lock'),
                                        str(self.root / 'markers'), writer_uid=10001, writer_gid=10001,
                                        controller_uid=1001, controller_gid=1001)

    def add_operation(self, op, sequence, outcome=None):
        operation = secure_dir(self.window / 'ops' / op)
        write_sealed(operation / 'candidate.json', dict(sequence=sequence, nonce=str(uuid.uuid4()), action='stop'))
        if outcome is not None:
            write_sealed(operation / 'result.json', dict(outcome=outcome, operation=op, window=WINDOW_ID))

    def set_authority(self, highest, bulky=(), small=()):
        """Bulky records carry a 180-byte pad; small records carry none."""
        intents = {}
        for sequence, pad in [(s, 'x' * 180) for s in bulky] + [(s, '') for s in small]:
            nonce = str(uuid.uuid4())
            intents[nonce] = dict(sequence=sequence, nonce=nonce, action='stop', pad=pad)
        (self.store / 'intent-authority.json').write_bytes(
            json.dumps(dict(highest_sequence=highest, rejected_sequences=[], intents=intents)).encode())

    def readiness(self, predecessor=PRED_OP):
        return self.ns['readiness_check'](self.custody, self.paths, str(self.window), WINDOW_ID, predecessor)

    def test_predecessor_floor_within_budget_passes_with_large_history_below_it(self):
        self.add_operation(PRED_OP, 341, 'published')
        self.set_authority(highest=341, bulky=range(1, 341), small=[341])
        result = self.readiness()
        self.assertEqual(set(result), {'predecessor_op', 'floor', 'status', 'elapsed_seconds', 'view_bytes', 'view_sha256'})
        self.assertEqual((result['predecessor_op'], result['floor'], result['status']), (PRED_OP, 341, 0))
        self.assertLess(result['view_bytes'], 60000)

    def test_newest_only_fits_but_predecessor_floor_overflows_refuses(self):
        self.add_operation(PRED_OP, 1, 'published')
        self.set_authority(highest=341, bulky=range(2, 342), small=[1])
        status, newest = self.custody.native_job(lambda: self.custody.view(self.paths, 'stop', None), 5)
        self.assertEqual(status, 0)
        self.assertLess(len(json.dumps(newest).encode()), 60000)
        with self.assertRaisesRegex(RuntimeError, 'readiness view unknown'):
            self.readiness()

    def test_predecessor_must_be_the_newest_candidate(self):
        self.add_operation(PRED_OP, 1, 'published')
        self.add_operation(OTHER_OP, 2, 'published')
        self.set_authority(highest=2, small=[1, 2])
        with self.assertRaisesRegex(RuntimeError, 'not the newest candidate'):
            self.readiness()

    def test_predecessor_must_be_published(self):
        self.add_operation(PRED_OP, 1, 'not-published')
        self.set_authority(highest=1, small=[1])
        with self.assertRaisesRegex(RuntimeError, 'unpublished'):
            self.readiness()

    def test_predecessor_without_a_result_refuses(self):
        self.add_operation(PRED_OP, 1, None)
        self.set_authority(highest=1, small=[1])
        with self.assertRaisesRegex(RuntimeError, 'unresolved'):
            self.readiness()

    def test_absent_predecessor_refuses(self):
        self.add_operation(OTHER_OP, 1, 'published')
        self.set_authority(highest=1, small=[1])
        with self.assertRaisesRegex(RuntimeError, 'not a candidate'):
            self.readiness()

    def test_pending_checkpoint_refuses(self):
        self.add_operation(PRED_OP, 1, 'published')
        self.set_authority(highest=1, small=[1])
        checkpoints = secure_dir(self.window / 'checkpoints')
        write_sealed(checkpoints / 'pending.json', dict(id=str(uuid.uuid4()), manifest_sha256='0' * 64))
        with self.assertRaisesRegex(RuntimeError, 'checkpoint pending'):
            self.readiness()

    def test_non_canonical_predecessor_refuses(self):
        self.add_operation(PRED_OP, 1, 'published')
        self.set_authority(highest=1, small=[1])
        with self.assertRaisesRegex(RuntimeError, 'canonical UUID'):
            self.readiness(predecessor=PRED_OP.upper())

    def test_sealed_custody_copy_must_match_its_pin(self):
        bad = secure_dir(self.root / 'bad')
        write_sealed(bad / 'owner-custody.py', (PROCEDURE / 'owner-custody.py').read_bytes() + b'#\n')
        with self.assertRaisesRegex(RuntimeError, 'pin mismatch'):
            self.ns['load_custody'](str(bad / 'owner-custody.py'))


if __name__ == '__main__':
    unittest.main()
