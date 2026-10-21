import ast
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

import build_long_window_native_r2 as restage
import build_window_checkpoint_r2 as gen

OP_A = str(uuid.UUID(int=1))
OP_B = str(uuid.UUID(int=2))
OP_C = str(uuid.UUID(int=3))
PRED_OP = OP_B
WID = gen.WINDOW_ID
WINDOW = gen.WINDOW
STAGE = gen.STAGE
OLD_STAGE = gen.OLD_STAGE
FORBIDDEN_CALLS = frozenset(('unlink', 'rmtree', 'remove', 'rename', 'replace', 'chmod', 'chown',
                             'fchmod', 'fchown', 'lchown', 'removedirs', 'renames'))
FORBIDDEN_SUBCOMMANDS = frozenset(('start', 'stop', 'auto', 'withdraw'))
FORBIDDEN_TOKENS = ('docker', 'systemctl', 'nvidia-smi')
SHARED_NAMES = ('STAGE', 'OLD_STAGE', 'WINDOW', 'WINDOW_ID', 'MANIFEST_SHA256', 'OWNER_CUSTODY_SHA256')
CHECKPOINT_ARGV = ['sudo', '-n', '-H', '-u', 'ubuntu', 'sudo', '-n', '/usr/bin/python3', '-I', '-B',
                   STAGE + '/owner-window.py', 'checkpoint', WINDOW, WID]
RECONCILE_ARGV = ['sudo', '-n', '-H', '-u', 'ubuntu', 'sudo', '-n', '/usr/bin/python3', '-I', '-B',
                  STAGE + '/owner-window.py', 'reconcile', WINDOW, WID]
# Stub custody: implements only the API the emitted program calls, over the tmp tree.
STUB_CUSTODY = b'''import json,os,pathlib,stat
FENCES=[]
class Paths:
    def __init__(self,runtime,store,lifecycle,markers,writer_uid=None,writer_gid=None,now=None,*,controller_uid=None,controller_gid=None):
        self.runtime=pathlib.Path(runtime)
    def fences(self,mode):
        return [pathlib.Path(p) for p in FENCES]
def read_file(fd,name):
    f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
    try:
        out=b''
        while True:
            chunk=os.read(f,65536)
            if not chunk: return out
            out+=chunk
    finally: os.close(f)
def subdir(fd,name):
    return os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
def load_json(fd,name): return json.loads(read_file(fd,name))
def validate_window(path,expected_id=None):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    window=load_json(fd,'window.json')
    return fd,window
def validate_procedure(wfd,window,procedure): return None
def known_candidates(wfd):
    ops=subdir(wfd,'ops'); known={}
    try:
        names=sorted(os.listdir(ops))
        if len(names)>32: raise RuntimeError('operation budget exhausted')
        for name in names:
            f=subdir(ops,name)
            try: known[name]=load_json(f,'candidate.json')
            except FileNotFoundError: pass
            finally: os.close(f)
    finally: os.close(ops)
    return known
def checkpoint_view(paths,floor):
    return dict(floor=floor,authority=None,publications={},loads=[],deferred=None),{}
def _checkpoint_fence(paths,path,window_lock,s):
    return stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==0 and stat.S_IMODE(s.st_mode)==0o660
'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def secure_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def write_sealed(path, value):
    raw = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True) + '\n').encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)


def make_fence(path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    os.chmod(path, 0o660)


def snapshot(root):
    return sorted((str(p.relative_to(root)), p.is_dir()) for p in Path(root).rglob('*'))


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
    """Exec the emitted program without its final run() call, so its helpers can be tested."""
    if not program.endswith('\nrun()\n'):
        raise AssertionError('generated program must end with run()')
    namespace = {'__name__': 'generated_program_under_test'}
    exec(compile(program[:-len('run()\n')], 'generated-program', 'exec'), namespace)
    namespace['ROOT_UID'] = os.geteuid()
    return namespace


def forbidden_findings(program):
    findings = []
    for node in ast.walk(ast.parse(program)):
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
            findings.append(node.attr)
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
            findings.append(node.id)
        if isinstance(node, ast.keyword) and node.arg == 'exist_ok':
            findings.append('exist_ok')
        if isinstance(node, (ast.List, ast.Tuple)):
            findings += [e.value for e in node.elts
                         if isinstance(e, ast.Constant) and e.value in FORBIDDEN_SUBCOMMANDS]
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            findings += [t for t in FORBIDDEN_TOKENS if t in node.value]
    return findings


def stage_files():
    names = sorted(gen.restage.SCRIPTS)
    scripts = {name: f'# {name}\n'.encode() for name in names}
    pins = {name: sha(raw) for name, raw in scripts.items()}
    manifest = (json.dumps(pins, sort_keys=True) + '\n').encode()
    files = dict(scripts)
    files['approved-scripts.json'] = manifest
    files['procedure-predecessor.json'] = b'{}\n'
    return files


class GeneratorConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def build(self, source=None):
        return gen.build(24, PRED_OP, Path(self.tmp.name), source)

    def test_config_fields_and_values_are_exact(self):
        config_path, program_path = self.build()
        config = json.loads(config_path.read_bytes())
        self.assertEqual(config, dict(
            name='BAKEOFF-WINDOW-CHECKPOINT-R2', owner='Bakeoff_LongLive',
            unit='workbay-bakeoff-window-checkpoint-r2-20261020.scope', model=None, cpu=0.5,
            memory=2147483648, forecast=1073741824, source=None, timeout=120,
            role='qualified_root_same_window_checkpoint_bounded_stage',
            program=str(program_path)))
        self.assertTrue(Path(config['program']).is_absolute())
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name).iterdir()),
                         sorted([gen.CONFIG_NAME, gen.PROGRAM_NAME]))

    def test_source_is_recorded_when_given(self):
        config_path, _ = self.build(source='b' * 40)
        self.assertEqual(json.loads(config_path.read_bytes())['source'], 'b' * 40)

    def test_transport_shape_matches_the_restage_config(self):
        source = Path(restage.__file__).read_text()
        restage_config = None
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'dict'
                    and any(k.arg == 'name' and isinstance(k.value, ast.Constant)
                            and k.value.value == 'BAKEOFF-LONG-WINDOW-NATIVE-R2' for k in node.keywords)):
                restage_config = node
        self.assertIsNotNone(restage_config)
        literal = {}
        for keyword in restage_config.keywords:
            try:
                literal[keyword.arg] = ast.literal_eval(keyword.value)
            except ValueError:
                literal[keyword.arg] = None
        config_path, _ = self.build()
        config = json.loads(config_path.read_bytes())
        self.assertEqual(set(config), {k.arg for k in restage_config.keywords})
        for name in ('owner', 'model', 'cpu', 'memory', 'forecast', 'timeout'):
            with self.subTest(name=name):
                self.assertEqual(config[name], literal[name])

    def test_shared_constants_are_imported_not_retyped(self):
        for name in SHARED_NAMES:
            with self.subTest(name=name):
                self.assertEqual(getattr(gen, name), getattr(restage, name))
        literals = {node.value for node in ast.walk(ast.parse(Path(gen.__file__).read_text()))
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for name in SHARED_NAMES:
            with self.subTest(retyped=name):
                self.assertNotIn(getattr(restage, name), literals)


class EmittedProgramTests(unittest.TestCase):
    def setUp(self):
        self.program = gen.render_program(PRED_OP, 24)

    def test_program_parses_and_ends_with_run(self):
        ast.parse(self.program)
        self.assertTrue(self.program.endswith('\nrun()\n'))

    def test_header_constants_are_literals_and_equal_the_shared_values(self):
        constants = program_constants(self.program)
        self.assertEqual(constants['PREVIOUS'], PRED_OP)
        self.assertEqual(constants['EXPECT_OPS'], 24)
        self.assertEqual(constants['STAGE'], STAGE)
        self.assertEqual(constants['OLD_STAGE'], OLD_STAGE)
        self.assertEqual(constants['WINDOW'], WINDOW)
        self.assertEqual(constants['WINDOW_ID'], WID)
        self.assertEqual(constants['MANIFEST_SHA256'], restage.MANIFEST_SHA256)
        self.assertEqual(constants['MANIFEST_SHA256'], 'cd399f1f0d55fd1dbf4eb980d0accbdb6b2ac27536f4f11a222b3262bdcbb495')
        self.assertEqual(constants['OWNER_CUSTODY_SHA256'], restage.OWNER_CUSTODY_SHA256)

    def test_checkpoint_and_reconcile_argv_are_exact(self):
        namespace = program_namespace(self.program)
        self.assertEqual(namespace['CHECKPOINT_ARGV'], CHECKPOINT_ARGV)
        self.assertEqual(namespace['RECONCILE_ARGV'], RECONCILE_ARGV)
        self.assertIsNone(namespace['BASE'])

    def test_stage_and_window_paths_are_embedded_literally(self):
        self.assertIn(repr(STAGE), self.program)
        self.assertIn(repr(WINDOW), self.program)
        self.assertIn(repr(OLD_STAGE), self.program)


class ForbiddenScanTests(unittest.TestCase):
    def setUp(self):
        self.program = gen.render_program(PRED_OP, 24)

    def test_emitted_program_has_no_forbidden_operations(self):
        self.assertEqual(forbidden_findings(self.program), [])

    def test_positive_control_injected_unlink_is_caught(self):
        injected = self.program.replace('\nrun()\n', "\nos.unlink('x')\nrun()\n")
        self.assertIn('unlink', forbidden_findings(injected))

    def test_positive_control_injected_rename_and_replace_are_caught(self):
        injected = self.program.replace('\nrun()\n', "\nos.rename('a','b')\n'x'.replace('a','b')\nrun()\n")
        self.assertIn('rename', forbidden_findings(injected))
        self.assertIn('replace', forbidden_findings(injected))

    def test_positive_control_exist_ok_is_caught(self):
        injected = self.program.replace('\nrun()\n', "\nos.makedirs('x',exist_ok=True)\nrun()\n")
        self.assertIn('exist_ok', forbidden_findings(injected))

    def test_positive_control_subcommand_argv_is_caught(self):
        injected = self.program.replace("'checkpoint',WINDOW", "'stop',WINDOW")
        self.assertIn('stop', forbidden_findings(injected))

    def test_positive_control_gpu_or_service_call_is_caught(self):
        injected = self.program.replace('\nrun()\n', "\nsubprocess.run(['systemctl','restart','x'])\nrun()\n")
        self.assertIn('systemctl', forbidden_findings(injected))

    def test_popen_is_called_only_from_the_owner_window_helper(self):
        tree = ast.parse(self.program)
        owners = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)
                  for n in ast.walk(node) if isinstance(n, ast.Attribute) and n.attr == 'Popen']
        self.assertEqual(owners, ['run_owner_window'])


class OrderingTests(unittest.TestCase):
    def test_guard_custody_readiness_inventory_checkpoint_reconcile_in_order(self):
        program = gen.render_program(PRED_OP, 24)
        run = next(node for node in ast.parse(program).body
                   if isinstance(node, ast.FunctionDef) and node.name == 'run')
        first = {}
        for node in ast.walk(run):
            if isinstance(node, ast.Name):
                first[node.id] = min(first.get(node.id, node.lineno), node.lineno)
        self.assertLess(first['verify_stage'], first['guard_window'])
        self.assertLess(first['guard_window'], first['load_custody'])
        self.assertLess(first['load_custody'], first['readiness'])
        self.assertLess(first['readiness'], first['before_inventory'])
        self.assertLess(first['before_inventory'], first['CHECKPOINT_ARGV'])
        self.assertLess(first['CHECKPOINT_ARGV'], first['RECONCILE_ARGV'])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'out'

    def run_cli(self, previous=PRED_OP, expect='24', extra=()):
        argv = ['--expect-ops', str(expect), '--previous-op', previous, '--out-dir', str(self.out), *extra]
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                gen.main(argv)
        return caught.exception.code

    def test_happy_path_writes_both_files_and_prints_their_paths(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            gen.main(['--expect-ops', '24', '--previous-op', PRED_OP, '--out-dir', str(self.out)])
        self.assertEqual(out.getvalue().splitlines(),
                         [str(self.out / gen.CONFIG_NAME), str(self.out / gen.PROGRAM_NAME)])
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted([gen.CONFIG_NAME, gen.PROGRAM_NAME]))

    def test_bad_previous_uuid_refuses_and_writes_nothing(self):
        self.assertEqual(self.run_cli(previous='not-a-uuid'), 2)
        self.assertFalse(self.out.exists())

    def test_upper_case_previous_uuid_refuses(self):
        self.assertEqual(self.run_cli(previous='A9E13611-F042-44E4-8AA4-2E81E6D19597'), 2)
        self.assertFalse(self.out.exists())

    def test_expect_ops_zero_refuses(self):
        self.assertEqual(self.run_cli(expect=0), 2)
        self.assertFalse(self.out.exists())

    def test_expect_ops_thirty_three_refuses(self):
        self.assertEqual(self.run_cli(expect=33), 2)
        self.assertFalse(self.out.exists())

    def test_expect_ops_non_integer_refuses(self):
        self.assertEqual(self.run_cli(expect='many'), 2)
        self.assertFalse(self.out.exists())

    def test_expect_ops_thirty_two_is_the_inclusive_bound(self):
        with contextlib.redirect_stdout(io.StringIO()):
            gen.main(['--expect-ops', '32', '--previous-op', PRED_OP, '--out-dir', str(self.out)])
        self.assertEqual(program_constants((self.out / gen.PROGRAM_NAME).read_text())['EXPECT_OPS'], 32)

    def test_existing_config_refuses_and_writes_no_program(self):
        self.out.mkdir()
        (self.out / gen.CONFIG_NAME).write_text('old\n')
        self.assertEqual(self.run_cli(), 2)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [gen.CONFIG_NAME])
        self.assertEqual((self.out / gen.CONFIG_NAME).read_text(), 'old\n')

    def test_existing_program_refuses_and_writes_no_config(self):
        self.out.mkdir()
        (self.out / gen.PROGRAM_NAME).write_text('old\n')
        self.assertEqual(self.run_cli(), 2)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), [gen.PROGRAM_NAME])
        self.assertEqual((self.out / gen.PROGRAM_NAME).read_text(), 'old\n')

    def test_malformed_source_refuses(self):
        self.assertEqual(self.run_cli(extra=('--source', 'ABC')), 2)
        self.assertFalse(self.out.exists())


class WindowWorldTests(unittest.TestCase):
    """Stub custody over a tmp window, with the real program helpers driving it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.window = secure_dir(self.root / 'window')
        self.evidence = secure_dir(self.root / 'evidence')
        self.ns = program_namespace(gen.render_program(PRED_OP, 2))
        self.ns.update(ROOT_UID=os.geteuid(), WINDOW=str(self.window), WINDOW_ID=WID, OLD_STAGE=str(self.root / 'old'),
                       STAGE=str(self.root / 'stage' / 'procedure'), PREVIOUS=PRED_OP, EXPECT_OPS=2)
        self.evidence_fd = os.open(str(self.evidence), os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.evidence_fd)
        self.ns['EVIDENCE'] = self.evidence_fd
        write_sealed(self.window / 'window.json',
                     dict(id=WID, path=str(self.window), procedure=str(self.root / 'old')))
        secure_dir(self.window / 'ops')
        self.add_op(OP_A, 1, 'published')
        self.add_op(OP_B, 2, 'published')
        fences = secure_dir(self.root / 'fences')
        self.fences = [fences / f'{name}.lock' for name in
                       ('lifecycle', 'gpu-0', 'gpu-1', 'gpu-2', 'gpu-3', 'gpu-4', 'authority')]
        for path in self.fences:
            make_fence(path)
        make_fence(self.window / 'window.lock')
        self.custody = self.load_stub()

    def add_op(self, op, sequence, outcome):
        operation = secure_dir(self.window / 'ops' / op)
        write_sealed(operation / 'candidate.json', dict(sequence=sequence, nonce=str(uuid.uuid4()), action='stop'))
        if outcome is not None:
            write_sealed(operation / 'result.json', dict(outcome=outcome, operation=op, window=WID))

    def load_stub(self):
        qualified = secure_dir(self.root / 'qualified-source')
        write_sealed(qualified / 'owner-custody.py', STUB_CUSTODY)
        self.ns['OWNER_CUSTODY_SHA256'] = sha(STUB_CUSTODY)
        custody = self.ns['load_custody'](str(qualified / 'owner-custody.py'))
        custody.FENCES = [str(p) for p in self.fences]
        return custody

    def paths(self):
        return self.custody.Paths('runtime', 'store', 'lifecycle', 'markers')

    def test_control_newest_published_predecessor_passes(self):
        self.assertEqual(self.ns['custody_proof'](self.custody), 2)

    def test_previous_not_newest_refuses(self):
        self.ns['PREVIOUS'] = OP_A
        with self.assertRaisesRegex(RuntimeError, 'not the newest published'):
            self.ns['custody_proof'](self.custody)

    def test_previous_unpublished_refuses(self):
        self.add_op(OP_C, 3, 'not-published')
        self.ns['PREVIOUS'] = OP_C
        with self.assertRaisesRegex(RuntimeError, 'not a published operation'):
            self.ns['custody_proof'](self.custody)

    def test_control_readiness_seals_read_only_evidence(self):
        floor = self.ns['custody_proof'](self.custody)
        self.ns['readiness'](self.custody, self.paths(), floor)
        sealed = json.loads((self.evidence / 'qualified-read-only-readiness.json').read_bytes())
        self.assertEqual(sealed['floor'], 2)
        self.assertEqual(sealed['previous'], PRED_OP)
        self.assertTrue(sealed['no_mutation'])
        self.assertTrue(sealed['not_a_locked_admission'])
        self.assertEqual(len(sealed['fences']), 8)

    def test_missing_fence_refuses_and_creates_nothing(self):
        missing = self.fences[0]
        os.unlink(missing)
        before_window = snapshot(self.window)
        before_root = snapshot(self.root)
        with self.assertRaises(FileNotFoundError):
            self.ns['readiness'](self.custody, self.paths(), 2)
        self.assertFalse(os.path.lexists(missing))
        self.assertEqual(snapshot(self.window), before_window)
        self.assertEqual(snapshot(self.root), before_root)
        self.assertEqual(os.listdir(self.evidence), [])

    def test_unsafe_fence_role_refuses_and_creates_nothing(self):
        os.chmod(self.fences[2], 0o644)
        before_root = snapshot(self.root)
        with self.assertRaisesRegex(RuntimeError, 'missing or unsafe checkpoint fence'):
            self.ns['readiness'](self.custody, self.paths(), 2)
        self.assertEqual(snapshot(self.root), before_root)
        self.assertEqual(os.listdir(self.evidence), [])

    def test_control_guard_passes_with_exact_ops_count(self):
        self.assertIsInstance(self.ns['guard_window'](), bytes)

    def test_ops_count_mismatch_refuses(self):
        self.ns['EXPECT_OPS'] = 3
        with self.assertRaisesRegex(RuntimeError, 'operation count mismatch'):
            self.ns['guard_window']()


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = stage_files()
        self.ns = program_namespace(gen.render_program(PRED_OP, 2))
        self.ns['MANIFEST_SHA256'] = sha(self.files['approved-scripts.json'])
        self.ns['OWNER_CUSTODY_SHA256'] = json.loads(self.files['approved-scripts.json'])['owner-custody.py']
        self.stage = self.root / 'stage' / 'procedure'
        secure_dir(self.stage)
        for name, raw in self.files.items():
            write_sealed(self.stage / name, raw)

    def test_control_exactly_nine_pinned_entries_verify(self):
        verified = self.ns['verify_stage'](str(self.stage))
        self.assertEqual(set(verified), set(self.ns['STAGE_NAMES']))
        self.assertEqual(len(verified), 9)

    def test_tenth_file_refuses(self):
        write_sealed(self.stage / 'extra.py', b'print(1)\n')
        with self.assertRaisesRegex(RuntimeError, 'over budget|exactly the 9'):
            self.ns['verify_stage'](str(self.stage))

    def test_missing_pinned_entry_refuses(self):
        os.unlink(self.stage / 'root-flow.sh')
        with self.assertRaisesRegex(RuntimeError, 'exactly the 9'):
            self.ns['verify_stage'](str(self.stage))

    def test_nine_entries_with_a_foreign_name_refuse(self):
        os.rename(self.stage / 'root-flow.sh', self.stage / 'root-flow.txt')
        with self.assertRaisesRegex(RuntimeError, 'exactly the 9'):
            self.ns['verify_stage'](str(self.stage))

    def test_script_pin_mismatch_refuses(self):
        tampered = self.root / 'tampered' / 'procedure'
        secure_dir(tampered)
        for name, raw in self.files.items():
            write_sealed(tampered / name, b'changed\n' if name == 'observe.py' else raw)
        with self.assertRaisesRegex(RuntimeError, 'stage pin mismatch: observe.py'):
            self.ns['verify_stage'](str(tampered))

    def test_absent_stage_refuses_and_is_never_created(self):
        absent = self.root / 'absent' / 'procedure'
        with self.assertRaises(FileNotFoundError):
            self.ns['verify_stage'](str(absent))
        self.assertFalse((self.root / 'absent').exists())


class ArchiveMultisetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'window'
        self.ns = program_namespace(gen.render_program(PRED_OP, 2))
        op = secure_dir(self.root / 'ops' / OP_A)
        write_sealed(op / 'intent.json', b'{"a":1}\n')
        write_sealed(op / 'result.json', b'{"outcome":"published"}\n')

    def test_archive_move_keeps_every_content_entry(self):
        before = self.ns['tree'](str(self.root))
        archive = secure_dir(self.root / 'checkpoints' / 'tx' / 'ops')
        os.rename(self.root / 'ops' / OP_A, archive / OP_A)
        after = self.ns['tree'](str(self.root))
        self.assertFalse(self.ns['multiset'](before) - self.ns['multiset'](after))

    def test_positive_control_a_deleted_entry_is_detected(self):
        before = self.ns['tree'](str(self.root))
        os.unlink(self.root / 'ops' / OP_A / 'result.json')
        after = self.ns['tree'](str(self.root))
        self.assertTrue(self.ns['multiset'](before) - self.ns['multiset'](after))


if __name__ == '__main__':
    unittest.main()
