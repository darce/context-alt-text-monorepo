import ast
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import build_long_window_native_r2 as gen

SOURCE = 'a' * 40
PROCEDURE = Path(__file__).resolve().parents[1] / 'qualifications' / 'owner-resume-start-r4'
FORBIDDEN = ('checkpoint', 'reconcile', 'rmtree', 'unlink', 'remove')
STDLIB = {'base64', 'hashlib', 'importlib', 'json', 'os', 'pathlib', 'stat', 'sys', 'time', 'uuid'}
EXPECTED_CONSTANTS = dict(
    STAGE='/root/bakeoff-owner-long-window-20261020-cd399f1f0d55/procedure',
    OLD_STAGE='/root/owner-stop-contract-r3/procedure',
    CURRENT_STAGE='/root/bakeoff-owner-long-window-20261019-45c86daf3bc3/procedure',
    WINDOW='/tmp/qwen-owner-window.rcqmefq9',
    WINDOW_ID='223eb2de-b63a-4b19-a31e-a34d07a8e187',
    EXPECT_OPS=24,
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


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def generate(self, tree=None, expect_ops=24, source=SOURCE):
        return gen.build(source, expect_ops, Path(self.tmp.name),
                         load_tree=lambda _: dict(real_tree() if tree is None else tree))

    def test_happy_path_writes_the_config_and_the_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, program_path = gen.build(SOURCE, 24, Path(tmp),
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
            gen.main(['--source', SOURCE, '--out-dir', self.tmp.name])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

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
                gen.build(SOURCE, 24, out, load_tree=lambda _: real_tree())
            self.assertEqual((out / gen.CONFIG_NAME).read_text(), '{}\n')
            self.assertFalse((out / gen.PROGRAM_NAME).exists())

    def test_existing_program_refuses_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / gen.PROGRAM_NAME).write_text('original\n')
            with self.assertRaisesRegex(gen.Refused, 'no overwrite'):
                gen.build(SOURCE, 24, out, load_tree=lambda _: real_tree())
            self.assertEqual((out / gen.PROGRAM_NAME).read_text(), 'original\n')
            self.assertFalse((out / gen.CONFIG_NAME).exists())


if __name__ == '__main__':
    unittest.main()
