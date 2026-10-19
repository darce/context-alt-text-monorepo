"""Real asset ancestry validation with native-shaped stat results; no root I/O."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import stat
import unittest
from unittest.mock import Mock, call, patch

import test_gpu_vllm_maintenance as old

m = old.m
HERE = Path(__file__).parent
# Read the supplied native producer before mocking any filesystem metadata.
NATIVE = json.loads((HERE.parents[1] / 'references/actual-native-cache-ancestry.json').read_text())
LEAF = 'qwen3-vl-8b-0c351dd01ed87e9c1b53cbc748cba10e6187ff3b'
OLD_DIR = Path('/opt/acx-gpu/bakeoff-owned-cache') / LEAF
PRIVATE_DIR = Path('/root/bakeoff-owned-cache') / LEAF


class NativeStatProducer:
    """Keep real Path predicates/lstat and os.stat_result field semantics.

    The capture's mode is permissions only: st_mode also needs S_IFDIR.
    Uncaptured / and /opt are explicitly modeled as root-owned mode 0755;
    unrelated stat fields come from a local directory before the stat seam.
    The prospective cache parent retains the captured root-owned mode 0700.
    """
    def __init__(self):
        template = list(HERE.stat())
        root = dict(uid=0, gid=0, mode=0o755, dev=NATIVE['leaf']['dev'])
        metadata = {
            OLD_DIR: NATIVE['leaf'],
            OLD_DIR.parent: NATIVE['cacheparent'],
            Path(NATIVE['old_ancestor']['path']): NATIVE['old_ancestor'],
            Path('/opt'): root,
            Path('/'): root,
            PRIVATE_DIR: NATIVE['leaf'],
            PRIVATE_DIR.parent: NATIVE['cacheparent'],
            Path(NATIVE['new_root']['path']): NATIVE['new_root'],
        }
        self.stats = {}
        for path, row in metadata.items():
            fields = template.copy()
            fields[0] = stat.S_IFDIR | row['mode']
            fields[2], fields[4], fields[5] = row['dev'], row['uid'], row['gid']
            self.stats[path] = os.stat_result(fields)
        self.links = {}
        self.calls = []

    def stat(self, path, *, follow_symlinks=True):
        self.calls.append((path, follow_symlinks))
        # Unknown paths fail the fixture rather than reaching the real filesystem.
        if not follow_symlinks and path in self.links:
            return self.links[path]
        return self.stats[path]

    def change(self, path, *, mode=None, uid=None, gid=None, symlink=False):
        fields = list(self.stats[path])
        if mode is not None:
            fields[0] = mode
        if uid is not None:
            fields[4] = uid
        if gid is not None:
            fields[5] = gid
        (self.links if symlink else self.stats)[path] = os.stat_result(fields)


class CacheAncestryTests(unittest.TestCase):
    def setUp(self):
        root = Path('/run') / ('bakeoff-vllm-' + old.OP.replace('-', ''))
        self.runner = Mock(side_effect=AssertionError('no native commands permitted'))
        self.runtime = m.Runtime(root, old.OP, root / 'spec.json', runner=self.runner)
        self.assertEqual((self.runtime.policy.uid, self.runtime.policy.gid), (0, 0))
        self.addCleanup(self.runner.assert_not_called)

    @contextmanager
    def fixture(self, model_dir):
        producer = NativeStatProducer()
        with patch.object(m, 'MODEL_DIR', model_dir), \
                patch.object(Path, 'stat', autospec=True, side_effect=producer.stat), \
                patch.object(self.runtime, 'validate_asset') as asset:
            yield producer, asset

    def assert_all_assets(self, producer, asset, model_dir):
        paths = (model_dir, *model_dir.parents)
        # lstat uses stat(follow_symlinks=False); is_dir uses a following stat.
        self.assertEqual(producer.calls, [(p, False) for p in paths] +
                         [(model_dir, True)] + [(p, True) for p in paths])
        self.assertEqual(len(m.ASSETS), 14)
        self.assertEqual(asset.call_args_list,
                         [call(model_dir / name, size, digest)
                          for name, (size, digest) in m.ASSETS.items()])

    def test_fixed_location_validates_all_fourteen_pins(self):
        # This executes the unchanged validator against the actual fixed path.
        # Before relocation of the source constant it fails on /opt/acx-gpu.
        with self.fixture(m.MODEL_DIR) as (producer, asset):
            self.runtime.validate_assets()
            self.assertEqual(m.MODEL_DIR, PRIVATE_DIR)
            self.assert_all_assets(producer, asset, PRIVATE_DIR)

    def test_old_native_operator_ancestor_is_refused_before_assets(self):
        with self.fixture(OLD_DIR) as (producer, asset):
            for path in (OLD_DIR, OLD_DIR.parent):
                observed = producer.stats[path]
                self.assertIsInstance(observed, os.stat_result)
                self.assertTrue(stat.S_ISDIR(observed.st_mode))
                self.assertEqual((observed.st_uid, observed.st_gid,
                                  stat.S_IMODE(observed.st_mode), observed.st_dev),
                                 (0, 0, 0o700, 2049))
            ancestor = producer.stats[Path('/opt/acx-gpu')]
            self.assertEqual((ancestor.st_uid, ancestor.st_gid,
                              stat.S_IMODE(ancestor.st_mode)), (1001, 1001, 0o755))
            with self.assertRaisesRegex(m.Refusal, '^' + NATIVE['actual_refusal'] + '$'):
                self.runtime.validate_assets()
            asset.assert_not_called()

    def test_prospective_private_ancestry_validates_all_fourteen_pins(self):
        # Also passes before the source constant changes: only ancestry differs.
        with self.fixture(PRIVATE_DIR) as (producer, asset):
            self.runtime.validate_assets()
            self.assert_all_assets(producer, asset, PRIVATE_DIR)

    def test_nonroot_ownership_at_every_directory_is_refused(self):
        for path in (PRIVATE_DIR, *PRIVATE_DIR.parents):
            with self.subTest(path=path), self.fixture(PRIVATE_DIR) as (producer, asset):
                producer.change(path, uid=1001, gid=1001)
                with self.assertRaisesRegex(m.Refusal, 'model directory ownership/mode refused'):
                    self.runtime.validate_assets()
                asset.assert_not_called()

    def test_group_and_world_writable_directories_are_refused(self):
        for path in (PRIVATE_DIR, *PRIVATE_DIR.parents):
            for writable in (0o020, 0o002):
                with self.subTest(path=path, writable=writable), \
                        self.fixture(PRIVATE_DIR) as (producer, asset):
                    producer.change(path, mode=producer.stats[path].st_mode | writable)
                    with self.assertRaisesRegex(m.Refusal, 'model directory ownership/mode refused'):
                        self.runtime.validate_assets()
                    asset.assert_not_called()

    def test_symlink_at_every_directory_is_refused_even_with_safe_target(self):
        for path in (PRIVATE_DIR, *PRIVATE_DIR.parents):
            with self.subTest(path=path), self.fixture(PRIVATE_DIR) as (producer, asset):
                producer.change(path, mode=stat.S_IFLNK | 0o777, symlink=True)
                with self.assertRaisesRegex(m.Refusal, 'model directory symlink refused'):
                    self.runtime.validate_assets()
                asset.assert_not_called()


if __name__ == '__main__':
    unittest.main()
