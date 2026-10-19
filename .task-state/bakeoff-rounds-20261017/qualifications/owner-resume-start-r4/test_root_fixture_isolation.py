"""Safe source controls; substituted UID/proc/mount/receipt data are NOT Root proof."""
import argparse
import copy
from contextlib import ExitStack
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('fixture_plan_test', HERE / 'root_fixture_plan.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
TARGETS = ('/run', '/var/lib', '/var/log', '/tmp', '/opt')
PARENT = dict(mnt='mnt:[10]', pid='pid:[11]', net='net:[12]')
CHILD = dict(mnt='mnt:[20]', pid='pid:[21]', net='net:[22]')


class ReachedStage(Exception):
    pass


def row(mid, target, device):
    return f'{mid} 1 {device} / {target} rw - tmpfs fixture rw'


class CausalDriverTests(unittest.TestCase):
    """Execute the whole driver, stopping before stage import or any subprocess.

    UID, ubuntu passwd, parent evidence, proc links/mountinfo and the NEW receipt
    reader/inventory are substituted. No privileged operation is executed.
    """
    def check_driver(self, inherited=False, uid=0, euid=0, ubuntu=1001,
                     pid=2, parent_mode=0o400, ns=None, propagation=''):
        lines = [row(i + 30, p, f'0:{i + 30}') for i, p in enumerate(TARGETS)]
        if not inherited:
            lines += [row(i + 60, p, f'0:{i + 60}') for i, p in enumerate(TARGETS)]
        if propagation:
            lines[0] = lines[0].replace(' rw - ', ' rw ' + propagation + ' - ')
        before, after = inventories()
        if inherited:
            after = before
        receipt = dict(version=1, creator=creator(), creator_fd=71, before=before, after=after)
        args = argparse.Namespace(parent_namespaces='/sealed/parent.json', overlay_receipt_fd=71,
                                  stage='/tmp/stage', window='/tmp/window', output='/tmp/output', expect='new-green')
        with ExitStack() as stack:
            for name, value in [('getuid', uid), ('geteuid', euid), ('getpid', pid), ('getppid', 1)]:
                stack.enter_context(patch.object(driver.os, name, return_value=value))
            stack.enter_context(patch.object(driver.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_uid=ubuntu, pw_gid=ubuntu)))
            stack.enter_context(patch.object(Path, 'lstat', return_value=types.SimpleNamespace(st_mode=stat.S_IFREG | parent_mode, st_uid=0, st_nlink=1, st_size=100)))
            stack.enter_context(patch.object(Path, 'read_bytes', return_value=json.dumps(PARENT).encode()))
            stack.enter_context(patch.object(Path, 'read_text', autospec=True,
                                           side_effect=lambda p: '2' if str(p).endswith('/children') else '\n'.join(lines)))
            stack.enter_context(patch.object(driver.os, 'readlink', side_effect=lambda p: (ns or CHILD)[p.rsplit('/', 1)[1]]))
            stack.enter_context(patch.object(driver, 'sealed_overlay_receipt', return_value=receipt, create=True))
            stack.enter_context(patch.object(driver, 'creator_identity', return_value=creator(), create=True))
            stack.enter_context(patch.object(driver, 'held_inventory', return_value=inventory_context(after), create=True))
            stack.enter_context(patch.object(driver.importlib.util, 'spec_from_file_location', side_effect=ReachedStage))
            driver.run(args)

    def test_valid_fresh_stacked_overlay(self):
        with self.assertRaises(ReachedStage):
            self.check_driver()

    def test_inherited_backing_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'fresh'):
            self.check_driver(inherited=True)

    def test_existing_entry_refusals(self):
        for kwargs, message in [({'uid': 1002}, 'actual Root'),
                                ({'euid': 1002}, 'actual Root'),
                                ({'ubuntu': 1002}, 'ubuntu1001'),
                                ({'pid': 1}, 'coordinator PID1'),
                                ({'parent_mode': 0o600}, 'sealed parent'),
                                ({'ns': PARENT}, 'fresh MNT/PID/NET'),
                                ({'propagation': 'shared:7'}, 'private propagation')]:
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(RuntimeError, message):
                    self.check_driver(**kwargs)


def creator():
    return dict(pid=1, starttime='1234', namespaces=CHILD)


def inventories():
    def inventory(offset):
        mounts = [dict(mount_id=i + offset, target=p, device=f'0:{i + offset}',
                       root='/', fstype='tmpfs') for i, p in enumerate(TARGETS)]
        return dict(namespaces=CHILD.copy(), mounts=mounts,
                    targets={p: dict(mounts[i], ino=1) for i, p in enumerate(TARGETS)})
    before, after = inventory(30), inventory(60)
    after['mounts'] = before['mounts'] + after['mounts']
    return before, after


def inventory_context(value):
    from contextlib import nullcontext
    return nullcontext(value)


class ReceiptTests(unittest.TestCase):
    """Substitute proc/FD metadata and inventory; exercise validation itself."""
    def setUp(self):
        self.before, self.after = inventories()
        self.receipt = dict(version=1, creator=creator(), creator_fd=71,
                            before=self.before, after=self.after)
        self.current = copy.deepcopy(self.after)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(driver.os, 'getppid', return_value=1))
        self.stack.enter_context(patch.object(driver.os, 'getpid', return_value=2))
        self.children = self.stack.enter_context(patch.object(Path, 'read_text', return_value='2'))
        self.stack.enter_context(patch.object(driver, 'creator_identity', return_value=creator()))
        self.stack.enter_context(patch.object(driver, 'sealed_overlay_receipt', side_effect=lambda fd: self.receipt))
        self.stack.enter_context(patch.object(driver, 'held_inventory', side_effect=lambda: inventory_context(self.current)))

    def check(self):
        driver.private_fixture(71, PARENT)

    def test_stacked_green(self):
        self.check()

    def test_inherited_even_with_new_mount_id(self):
        self.after['targets']['/run']['device'] = self.before['targets']['/run']['device']
        with self.assertRaisesRegex(RuntimeError, 'fresh overlay backing'):
            self.check()

    def test_stale_mount_id(self):
        self.after['targets']['/run']['mount_id'] = 30
        with self.assertRaisesRegex(RuntimeError, 'fresh overlay backing'):
            self.check()

    def test_visible_descriptor_mismatch(self):
        for field, value in [('mount_id', 999), ('ino', 999), ('device', '0:999')]:
            with self.subTest(field=field):
                self.current = copy.deepcopy(self.after)
                self.current['targets']['/run'][field] = value
                with self.assertRaisesRegex(RuntimeError, 'visible descriptor receipt mismatch'):
                    self.check()

    def test_stale_creator(self):
        self.receipt['creator']['starttime'] = 'old'
        with self.assertRaisesRegex(RuntimeError, 'creator receipt'):
            self.check()

    def test_namespace_mismatch(self):
        self.receipt['before']['namespaces']['mnt'] = 'mnt:[stale]'
        with self.assertRaisesRegex(RuntimeError, 'namespace mismatch'):
            self.check()

    def test_parent_namespace_reused(self):
        with self.assertRaisesRegex(RuntimeError, 'fresh MNT/PID/NET'):
            driver.private_fixture(71, CHILD)

    def test_non_tmpfs_or_subdirectory(self):
        for field, value in [('fstype', 'ext4'), ('root', '/subdir')]:
            with self.subTest(field=field):
                self.after['targets']['/run'][field] = value
                with self.assertRaisesRegex(RuntimeError, 'fresh tmpfs root'):
                    self.check()
                self.after['targets']['/run'][field] = 'tmpfs' if field == 'fstype' else '/'

    def test_receipt_row_mismatch(self):
        self.after['mounts'] = self.before['mounts']
        with self.assertRaisesRegex(RuntimeError, 'receipt visible mount mismatch'):
            self.check()

    def test_incomplete_targets(self):
        del self.after['targets']['/opt']
        with self.assertRaisesRegex(RuntimeError, 'complete overlay targets'):
            self.check()

    def test_non_pid1_parent(self):
        with patch.object(driver.os, 'getppid', return_value=8):
            with self.assertRaisesRegex(RuntimeError, 'PID1 parent'):
                self.check()

    def test_other_native_child(self):
        self.children.return_value = '2 3'
        with self.assertRaisesRegex(RuntimeError, 'sole native child'):
            self.check()


class SealedReceiptBoundaryTests(unittest.TestCase):
    """Substitute fstat/fcntl/pread/PID1 FD stat; no actual Root/memfd claim."""
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.meta = types.SimpleNamespace(st_mode=stat.S_IFREG | 0o400, st_uid=0, st_nlink=0,
                                         st_size=100, st_dev=9, st_ino=10)
        self.stack.enter_context(patch.object(driver.os, 'fstat', return_value=self.meta))
        self.seals = self.stack.enter_context(patch.object(driver.fcntl, 'fcntl', return_value=15))
        self.stack.enter_context(patch.object(driver.os, 'pread', return_value=b'{"creator_fd":71}', create=True))
        self.owner = self.stack.enter_context(patch.object(driver.os, 'stat', return_value=self.meta))

    def test_sealed_receipt_green(self):
        self.assertEqual(driver.sealed_overlay_receipt(71), {'creator_fd': 71})

    def test_missing_fd(self):
        with self.assertRaisesRegex(RuntimeError, 'receipt FD'):
            driver.sealed_overlay_receipt(None)

    def test_missing_any_seal(self):
        for bit in (1, 2, 4, 8):
            with self.subTest(bit=bit):
                self.seals.return_value = 15 ^ bit
                with self.assertRaisesRegex(RuntimeError, 'immutable overlay receipt'):
                    driver.sealed_overlay_receipt(71)

    def test_wrong_creator_held_fd(self):
        self.owner.return_value = types.SimpleNamespace(st_dev=9, st_ino=11)
        with self.assertRaisesRegex(RuntimeError, 'creator-held receipt mismatch'):
            driver.sealed_overlay_receipt(71)

    def test_protected_receipt_metadata(self):
        for field, value in [('st_uid', 1002), ('st_mode', stat.S_IFREG | 0o600),
                             ('st_nlink', 1), ('st_size', 1048577)]:
            with self.subTest(field=field):
                previous = getattr(self.meta, field)
                setattr(self.meta, field, value)
                with self.assertRaisesRegex(RuntimeError, 'sealed Root memfd'):
                    driver.sealed_overlay_receipt(71)
                setattr(self.meta, field, previous)


class DescriptorBoundaryTests(unittest.TestCase):
    """Substitute open/close/fstat/fdinfo/mountinfo; ensure real data edges."""
    def inventory(self, mid=60, target='/run', device='0:60'):
        rows = [dict(mount_id=30, target='/run', device='0:30', root='/', fstype='tmpfs'),
                dict(mount_id=60, target=target, device=device, root='/', fstype='tmpfs')]
        with ExitStack() as stack:
            stack.enter_context(patch.object(driver, 'TARGETS', ('/run',)))
            stack.enter_context(patch.object(driver, 'mount_rows', return_value=rows))
            stack.enter_context(patch.object(driver, 'namespaces', return_value=CHILD))
            opened = stack.enter_context(patch.object(driver.os, 'open', side_effect=[100, 101]))
            closed = stack.enter_context(patch.object(driver.os, 'close'))
            stack.enter_context(patch.object(Path, 'read_text', return_value=f'mnt_id:\t{mid}\n'))
            stack.enter_context(patch.object(driver.os, 'fstat', return_value=types.SimpleNamespace(
                st_dev=os.makedev(0, 60), st_ino=1, st_mode=stat.S_IFDIR | 0o755)))
            with driver.held_inventory() as inventory:
                self.assertEqual(inventory['targets']['/run']['mount_id'], 60)
                self.assertNotIn(unittest.mock.call(101), closed.call_args_list)
                self.assertTrue(opened.call_args.args[1] & os.O_NOFOLLOW)
            self.assertIn(unittest.mock.call(101), closed.call_args_list)

    def test_held_descriptor_green(self):
        self.inventory()

    def test_wrong_descriptor_mount_id(self):
        with self.assertRaisesRegex(RuntimeError, 'visible descriptor mount mismatch'):
            self.inventory(mid=999)

    def test_covered_descriptor_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'visible descriptor device mismatch'):
            self.inventory(mid=30)

    def test_wrong_descriptor_target(self):
        with self.assertRaisesRegex(RuntimeError, 'visible descriptor mount mismatch'):
            self.inventory(target='/other')

    def test_wrong_descriptor_device(self):
        with self.assertRaisesRegex(RuntimeError, 'visible descriptor device mismatch'):
            self.inventory(device='0:99')

    def test_propagation_refusal(self):
        for tag in ('shared:2', 'master:2'):
            with self.subTest(tag=tag), patch.object(Path, 'read_text', return_value=
                    f'60 1 0:60 / /run rw {tag} - tmpfs fixture rw'):
                with self.assertRaisesRegex(RuntimeError, 'private propagation'):
                    driver.mount_rows()

    def test_actual_uid_refusal_boundary(self):
        # UID is explicitly substituted, even if the caller happens to be Root.
        with patch.object(driver.os, 'getuid', return_value=1002):
            with self.assertRaisesRegex(RuntimeError, 'actual Root required'):
                driver.run(types.SimpleNamespace())


class CoordinatorPreparationTests(unittest.TestCase):
    """Substitute complete harness, UID/PID, source custody and memfd syscalls.

    This checks passive bracketing/data flow only, never actual namespace setup.
    """
    def test_original_fixture_bracket_and_receipt_sealing(self):
        from unittest.mock import Mock
        spec = importlib.util.spec_from_file_location('fixture_coordinator_test', HERE.parents[1] / 'root_resume_fixture_coordinator.py')
        coordinator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(coordinator)
        before, after = inventories()
        events = []
        original = Mock(side_effect=lambda *args: events.append('whole-original-fixture') or '/tmp/stage')
        h = types.SimpleNamespace(capabilities=Mock(), HELD=[], directory=Mock(return_value=50),
                                  stage_read=Mock(return_value=({}, {})), bundle_read=Mock(return_value={}),
                                  flow=Mock(), fixture=original, children=Mock(return_value=[]), put=Mock())

        def inventory(*, before_fixture=False):
            from contextlib import contextmanager
            @contextmanager
            def capture():
                label = 'before' if not events else 'after'
                self.assertEqual(before_fixture, label == 'before')
                events.append(label + '-held')
                yield before if label == 'before' else after
                events.append(label + '-closed')
            return capture()

        d = types.SimpleNamespace(creator_identity=Mock(side_effect=creator), held_inventory=inventory,
                                  fresh_overlays=driver.fresh_overlays, RECEIPT_SEALS=15)

        def namespace_child(args, scripts, ids, raw):
            self.assertEqual(h.fixture('/root/unit/old-procedure', scripts, ids, Path('/root/unit/out')), '/tmp/stage')
            return 0

        h.namespace_child = namespace_child
        data_written = bytearray()
        with ExitStack() as stack:
            stack.enter_context(patch.object(coordinator.sys, 'argv', ['coordinator', '--input-root', '/root/unit',
                '--manifest-sha256', 'unit', '--case', 'old-red', '--output', '/root/unit/out',
                '--parent-namespaces', '/root/unit/parent.json']))
            for name, value in [('getuid', 0), ('geteuid', 0), ('getpid', 1)]:
                stack.enter_context(patch.object(coordinator.os, name, return_value=value))
            stack.enter_context(patch.object(coordinator.os, 'umask'))
            sealed = stack.enter_context(patch.object(coordinator, 'sealed', return_value=b'{"files":{}}'))
            loaded = stack.enter_context(patch.object(coordinator, 'load', side_effect=[h, d]))
            stack.enter_context(patch.object(coordinator.os, 'memfd_create', return_value=71, create=True))
            stack.enter_context(patch.object(coordinator.os, 'MFD_CLOEXEC', 1, create=True))
            stack.enter_context(patch.object(coordinator.os, 'MFD_ALLOW_SEALING', 2, create=True))
            stack.enter_context(patch.object(coordinator.os, 'write', side_effect=lambda fd, data:
                data_written.extend(data) or len(data)))
            mode = stack.enter_context(patch.object(coordinator.os, 'fchmod'))
            seal = stack.enter_context(patch.object(coordinator.fcntl, 'fcntl'))
            self.assertEqual(coordinator.main(), 0)
            sealed.assert_any_call(Path('/root/unit/OWNER-FLOW-CONTROLS-R2.py'), coordinator.FLOW_SHA256)
            self.assertEqual(loaded.call_args_list[0].args,
                             ('complete_prior_root_flow', Path('/root/unit/OWNER-FLOW-CONTROLS-R2.py')))
            mode.assert_called_once_with(71, 0o400)
            self.assertEqual(seal.call_args.args[0], 71)
            self.assertEqual(seal.call_args.args[2], 15)
        self.assertEqual(events, ['before-held', 'whole-original-fixture', 'after-held', 'after-closed', 'before-closed'])
        original.assert_called_once()
        receipt = json.loads(data_written)
        self.assertEqual(receipt, dict(version=1, creator=creator(), creator_fd=71, before=before, after=after))
        self.assertIn(71, h.HELD)


class OrdinaryPreparationTests(unittest.TestCase):
    """UNIT: real open/close/fdinfo/fstat and complete read-only mount inventory.

    Substitute private propagation (parse the actual rows without its refusal),
    UID/EUID/PID, creator identity, source custody, umask and complete harness.
    The original-fixture sentinel replaces the privileged body and stops before
    any mounts, receipt creation, subprocess or namespace operation.
    """
    def test_unit_ordinary_and_mixed_preparation(self):
        from unittest.mock import Mock

        class ReachedFixture(Exception):
            pass

        rows = []
        for line in Path('/proc/self/mountinfo').read_text().splitlines():
            left, right = line.split(' - ')
            fields = left.split()
            rows.append(dict(mount_id=int(fields[0]), device=fields[2], root=fields[3],
                             target=fields[4], fstype=right.split()[0]))
        spec = importlib.util.spec_from_file_location('ordinary_coordinator_test', HERE.parents[1] / 'root_resume_fixture_coordinator.py')
        coordinator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(coordinator)
        ordinary = ('/var/lib', '/var/log', '/opt')
        for layout, targets in [('ordinary-on-root', ordinary), ('mixed-five-targets', TARGETS)]:
            with self.subTest(layout=layout), ExitStack() as stack:
                original = Mock(side_effect=ReachedFixture)
                h = types.SimpleNamespace(capabilities=Mock(), HELD=[], directory=Mock(return_value=50),
                    stage_read=Mock(return_value=({}, {})), bundle_read=Mock(return_value={}),
                    flow=Mock(), fixture=original, children=Mock(return_value=[]), put=Mock())
                h.namespace_child = lambda args, scripts, ids, raw: h.fixture(
                    '/root/unit/old-procedure', scripts, ids, Path('/root/unit/out'))
                stack.enter_context(patch.object(coordinator.sys, 'argv', ['coordinator', '--input-root', '/root/unit',
                    '--manifest-sha256', 'unit', '--case', 'old-red', '--output', '/root/unit/out',
                    '--parent-namespaces', '/root/unit/parent.json']))
                for name, value in [('getuid', 0), ('geteuid', 0), ('getpid', 1)]:
                    stack.enter_context(patch.object(coordinator.os, name, return_value=value))
                stack.enter_context(patch.object(coordinator.os, 'umask'))
                stack.enter_context(patch.object(coordinator, 'sealed', return_value=b'{"files":{}}'))
                stack.enter_context(patch.object(coordinator, 'load', side_effect=[h, driver]))
                stack.enter_context(patch.object(driver, 'creator_identity', return_value=creator()))
                stack.enter_context(patch.object(driver, 'mount_rows', return_value=rows))
                stack.enter_context(patch.object(driver, 'TARGETS', targets))
                with self.assertRaises(ReachedFixture):
                    coordinator.main()
                original.assert_called_once()

                # After/current must still reject these real ordinary directories.
                with self.assertRaisesRegex(RuntimeError, 'visible descriptor mount mismatch: /var/lib'):
                    with driver.held_inventory():
                        pass
                with driver.held_inventory(before_fixture=True) as before:
                    self.assertEqual(before['mounts'], rows)  # complete, not just target rows
                    self.assertEqual(set(before['targets']), set(targets))
                    for target in ordinary:
                        visible = before['targets'][target]
                        self.assertEqual(visible['target'], '/')
                        self.assertEqual(visible['ino'], os.stat(target).st_ino)
                    if layout == 'mixed-five-targets':
                        self.assertEqual(before['targets']['/run']['target'], '/run')

                    # Only the post-mount data are synthetic; covered lower rows
                    # survive, and even non-target before backing stays forbidden.
                    after = copy.deepcopy(before)
                    old_devices = {r['device'] for r in rows}
                    offset = max(r['mount_id'] for r in rows) + 1
                    minor = max(int(d.split(':')[1]) for d in old_devices) + 1
                    for i, target in enumerate(targets):
                        mounted = dict(mount_id=offset + i, device=f'0:{minor + i}',
                                       target=target, root='/', fstype='tmpfs')
                        after['mounts'].append(mounted)
                        after['targets'][target] = dict(mounted, ino=1)
                    driver.fresh_overlays(before, after)
                    target_devices = {r['device'] for r in before['targets'].values()}
                    inherited = next(r['device'] for r in rows if r['device'] not in target_devices)
                    after['targets'][targets[0]]['device'] = inherited
                    after['mounts'][len(rows)]['device'] = inherited
                    with self.assertRaisesRegex(RuntimeError, 'fresh overlay backing'):
                        driver.fresh_overlays(before, after)


if __name__ == '__main__':
    unittest.main()
