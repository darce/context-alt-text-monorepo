"""Tests for cohort_admission and run_qwen_cohort_operation (decision 18673): stdlib only, no ssh, network or GPU."""
import ast
import hashlib
import importlib.util
import inspect
import io
import json
import os
import subprocess
import sys
import tarfile
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

QWEN_AB = Path(__file__).resolve().parent
G = 1024**3
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
CUSTODY_SOURCE = '22b61b6c7bc3932378dcb7e795a99f3ab288ff58'
BANNED = ['run_owner_root_fixture_r6', 'bakeoff_frontier_capacity', 'orchestrate', 'run_selected_root_resume_qualification']
TRANSIENT = {'cpu_pressure', 'io_pressure', 'memory_headroom', 'disk_projection', 'co_tenant_reserve', 'probe_transport'}
DETERMINISTIC = {'ledger_state', 'setup_owner', 'expired_owner_lease', 'root_probe', 'owned_unit_over_quota',
                 'co_tenant_unbounded', 'gpu_not_stopped', 'live_start', 'predecessor_unsettled', 'malformed_payload',
                 'source_unavailable'}


def load(name):
    spec = importlib.util.spec_from_file_location(name, QWEN_AB/(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CA = load('cohort_admission')
sys.modules['cohort_admission'] = CA  # the runner imports cohort_admission by name inside classify_preclaim
RUN = load('run_qwen_cohort_operation')


def refusal(cls, detail='x'):
    return CA.AdmissionRefusal(cls, detail)


def ledger(**extra):
    base = dict(pending_reservations_complete=True, Bakeoff=dict(remaining_actor_claim=0, reserved_now=False),
                setup_owner=None, aura=dict(active_models=[], setup_granted=False),
                Canvas=dict(active_models=[], setup_granted=False), wb={}, aura_runtime={}, WB_operations={},
                pending_reservations=[], runtime_reserve_bytes=3*G, emergency_reserve_bytes=1400000000)
    base.update(extra)
    return base


def owner_row(key='own', expires='2026-10-20T13:00:00+00:00', cpu=.25, mem=G):
    return dict(remaining_actor_claim=1, aggregate_cpu_cores_max=cpu, aggregate_memory_bytes_max=mem,
                physical_key=key, expires=expires, setup_granted=False)


PROFILE = dict(aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=2*G)


def root(pct='25%', used_kb=52428800, free_kb=157286400, **extra):
    base = dict(euid=0, hits=[], unknown=[], pg_all_healthy=True,
                df=f'Filesystem 1K-blocks Used Available Use% Mounted on\n/dev/root 209715200 {used_kb} {free_kb} {pct} /\n')
    base.update(extra)
    return base


def native(units=(), cpu='some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n',
           io='full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n', avail=8*G, headroom=8*G):
    return dict(units=list(units), cpu=cpu, io=io, physical_mem_available=avail, working_headroom=headroom)


def co(name, cpu='1s', mem='4294967296'):
    return dict(unit=f'workbay-lane-other-{name}.scope', CPUQuotaPerSecUSec=cpu, MemoryMax=mem)


def healthy(**over):
    args = dict(ledger=ledger(), profile=PROFILE, root=root(), native=native(), now=NOW)
    args.update(over)
    return CA.evaluate(**args)


# --- import safety and static rules -------------------------------------------------------------

def test_loading_both_modules_imports_no_admission_stack():
    code = ('import importlib.util as u, json, sys\n'
            'for path in %r:\n'
            ' s = u.spec_from_file_location("m", path); m = u.module_from_spec(s); s.loader.exec_module(m)\n'
            'print(json.dumps([n for n in %r if n in sys.modules]))\n') % (
        [str(QWEN_AB/'cohort_admission.py'), str(QWEN_AB/'run_qwen_cohort_operation.py')], BANNED)
    out = subprocess.run([sys.executable, '-I', '-B', '-c', code], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == []


def test_cohort_admission_has_no_bare_assert():
    tree = ast.parse((QWEN_AB/'cohort_admission.py').read_text())
    assert [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Assert)] == []


# --- refusal labels -----------------------------------------------------------------------------

def test_refusal_string_and_attributes():
    e = CA.AdmissionRefusal('cpu_pressure', 'x')
    assert str(e) == 'refusal:cpu_pressure: x'
    assert (e.cls, e.detail, e.transient) == ('cpu_pressure', 'x', True)
    assert CA.AdmissionRefusal('setup_owner', 'y').transient is False


def test_unknown_refusal_class_is_rejected():
    with pytest.raises(ValueError):
        CA.AdmissionRefusal('bare', 'x')


def test_transient_and_deterministic_sets_are_exact():
    assert CA.TRANSIENT == frozenset(TRANSIENT)
    assert CA.DETERMINISTIC == frozenset(DETERMINISTIC)
    assert all(CA.AdmissionRefusal(c, 'x').transient for c in TRANSIENT)
    assert not any(CA.AdmissionRefusal(c, 'x').transient for c in DETERMINISTIC)


def test_source_unavailable_is_deterministic_not_transient_and_admit_never_retries_it():
    assert 'source_unavailable' in CA.DETERMINISTIC
    assert 'source_unavailable' not in CA.TRANSIENT and 'source_unavailable' not in CA.EVALUATED
    tries = []

    def attempt():
        tries.append(1)
        raise CA.AdmissionRefusal('source_unavailable', 'x')

    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.admit(attempt=attempt, sleep=lambda seconds: None)
    assert e.value.cls == 'source_unavailable' and e.value.transient is False and tries == [1]


# --- parsers ------------------------------------------------------------------------------------

@pytest.mark.parametrize('value,expected', [('250ms', .25), ('1s', 1.), ('500000us', .5)])
def test_parse_cpu_quota(value, expected):
    assert CA.parse_cpu_quota(value) == pytest.approx(expected)


@pytest.mark.parametrize('value', ['infinity', '', 'banana'])
def test_parse_cpu_quota_returns_none_when_unbounded_or_unparseable(value):
    assert CA.parse_cpu_quota(value) is None


def test_parse_memory_max():
    assert CA.parse_memory_max('4294967296') == 4294967296
    assert CA.parse_memory_max('infinity') is None
    assert CA.parse_memory_max('banana') is None


@pytest.mark.parametrize('text,row,expected', [
    ('some avg10=1.00 avg60=12.50 avg300=0.00 total=0\n', 'some', 12.5),
    ('some avg10=1.00 avg60=12.50 avg300=0.00 total=0\nfull avg10=0.00 avg60=3 avg300=0.00 total=0\n', 'full', 3.),
])
def test_avg60_reads_the_row_named_by_its_leading_word(text, row, expected):
    assert CA.avg60(text, row) == pytest.approx(expected)


@pytest.mark.parametrize('text,row', [
    ('some avg10=0.00 avg60=0garbage avg300=0.00 total=0\n', 'some'),
    ('some avg10=0.00 avg60=. avg300=0.00 total=0\n', 'some'),
    ('some avg10=0.00 avg60=1..2 avg300=0.00 total=0\n', 'some'),
    ('some avg10=0.00 avg60=nan avg300=0.00 total=0\n', 'some'),
    ('some avg10=0.00 avg60=inf avg300=0.00 total=0\n', 'some'),
    ('some avg10=0.00 avg60=-1 avg300=0.00 total=0\n', 'some'),
    ('full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n', 'some'),
    ('', 'some'),
])
def test_avg60_is_infinite_for_any_malformed_or_absent_reading(text, row):
    assert CA.avg60(text, row) == float('inf')


# --- classify_native_units ----------------------------------------------------------------------

def test_classify_owned_unit_within_caps_passes():
    out = CA.classify_native_units([dict(unit='workbay-lane-own-r3.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))],
                                   {'workbay-lane-own': [.5, 2*G]})
    assert out['owned']['workbay-lane-own'][0] == pytest.approx(.25)
    assert out['owned']['workbay-lane-own'][1] == G
    assert out['co_tenant'] == [] and out['refusals'] == []


def test_classify_owned_unit_over_caps_raises():
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_native_units([dict(unit='workbay-lane-own-r3.scope', CPUQuotaPerSecUSec='1s', MemoryMax=str(G))],
                                 {'workbay-lane-own': [.5, 2*G]})
    assert e.value.cls == 'owned_unit_over_quota'


def test_classify_owned_unit_without_bounds_raises():
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_native_units([dict(unit='workbay-lane-own-r3.scope', CPUQuotaPerSecUSec='infinity', MemoryMax=str(G))],
                                 {'workbay-lane-own': [.5, 2*G]})
    assert e.value.cls == 'owned_unit_over_quota'


def test_classify_admits_bounded_co_tenant_and_lists_it():
    out = CA.classify_native_units([co('abc')], {'workbay-lane-own': [.5, 2*G]})
    assert out['co_tenant'] == [dict(unit='workbay-lane-other-abc.scope', cpu=1.0, memory=4294967296)]


@pytest.mark.parametrize('cpu,mem', [('infinity', '4294967296'), ('1s', 'infinity')])
def test_classify_unbounded_co_tenant_names_the_unit(cpu, mem):
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_native_units([co('abc', cpu=cpu, mem=mem)], {'workbay-lane-own': [.5, 2*G]})
    assert e.value.cls == 'co_tenant_unbounded'
    assert 'workbay-lane-other-abc.scope' in e.value.detail


OWN = {'workbay-lane-own': [.5, 2*G]}


def test_classify_foreign_unit_sharing_the_key_prefix_is_a_co_tenant():
    out = CA.classify_native_units([dict(unit='workbay-lane-owner.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))], OWN)
    assert out['owned']['workbay-lane-own'] == [0., 0]
    assert [c['unit'] for c in out['co_tenant']] == ['workbay-lane-owner.scope']


@pytest.mark.parametrize('unit', ['workbay-lane-own.scope', 'workbay-lane-own-sv.scope', 'workbay-lane-own-r3.scope',
                                  'workbay-lane-own-r3-sv.service'])
def test_classify_the_orchestrator_unit_forms_are_owned(unit):
    out = CA.classify_native_units([dict(unit=unit, CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))], OWN)
    assert out['owned']['workbay-lane-own'][0] == pytest.approx(.25)
    assert out['owned']['workbay-lane-own'][1] == G and out['co_tenant'] == []


def test_classify_an_exact_custody_unit_name_is_owned():
    out = CA.classify_native_units([dict(unit='workbay-custody-abc.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))],
                                   {'workbay-custody-abc.scope': [.5, 2*G]})
    assert out['owned']['workbay-custody-abc.scope'][1] == G and out['co_tenant'] == []


# --- root named units: the remote probe reports, and the verdict is classified here -------------

ROOT_UNIT = 'workbay-lane-own-r3.scope'
ROOT_CAPS = {ROOT_UNIT: [.5, 2*G]}
NOT_FOUND = dict(LoadState='not-found', ActiveState='inactive', ControlGroup='', MainPID='0',
                 CPUQuotaPerSecUSec='infinity', MemoryMax='infinity')


def named(total_cpu=.25, total_memory=G, invalid=()):
    return dict(system=dict(LoadState='loaded'), total_cpu=total_cpu, total_memory=total_memory, invalid_not_found=list(invalid))


def loaded(cpu='250ms', mem=str(G)):
    return dict(LoadState='loaded', ActiveState='active', ControlGroup='/user.slice/x.scope', MainPID='42',
                CPUQuotaPerSecUSec=cpu, MemoryMax=mem)


def test_classify_root_named_admits_units_within_caps():
    CA.classify_root_named({ROOT_UNIT: named()}, ROOT_CAPS)


def test_classify_root_named_tolerates_float_noise_on_the_cpu_cap():
    CA.classify_root_named({ROOT_UNIT: named(total_cpu=.5 + 1e-9)}, ROOT_CAPS)


@pytest.mark.parametrize('over', [dict(total_cpu=.75), dict(total_memory=3*G), dict(total_cpu=None), dict(total_memory=None)],
                         ids=['over cpu cap', 'over memory cap', 'unbounded cpu', 'memory infinity'])
def test_classify_root_named_refuses_over_quota_or_unbounded(over):
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_root_named({ROOT_UNIT: named(**over)}, ROOT_CAPS)
    assert e.value.cls == 'owned_unit_over_quota'


def test_classify_root_named_refuses_an_invalid_not_found_row():
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_root_named({ROOT_UNIT: named(invalid=['gate-user'])}, ROOT_CAPS)
    assert e.value.cls == 'root_probe'


def test_classify_root_named_refuses_a_missing_probe_row():
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_root_named({}, ROOT_CAPS)
    assert e.value.cls == 'root_probe'


def run_root_named(monkeypatch, capsys, shown, units=ROOT_CAPS):
    """Runs ROOT_NAMED_SCRIPT locally. shown is {namespace: {unit: row}}; a unit missing from it is not-found."""
    def check_output(cmd, text=True, timeout=None):
        namespace = 'system' if cmd[0] == 'systemctl' else 'gate-user'
        row = shown.get(namespace, {}).get(cmd[cmd.index('show') + 1], NOT_FOUND)
        return ''.join(f'{k}={v}\n' for k, v in row.items())
    monkeypatch.setattr(subprocess, 'check_output', check_output)
    exec(compile(CA.ROOT_NAMED_SCRIPT.replace('UNITS', repr(units)), 'root_named', 'exec'), {})
    return json.loads(capsys.readouterr().out)


def test_root_named_script_reports_raw_values_and_totals(monkeypatch, capsys):
    out = run_root_named(monkeypatch, capsys, dict(system={ROOT_UNIT: loaded()}))
    assert out[ROOT_UNIT]['system']['CPUQuotaPerSecUSec'] == '250ms'
    assert out[ROOT_UNIT]['gate-user']['LoadState'] == 'not-found'
    assert out[ROOT_UNIT]['total_cpu'] == pytest.approx(.25)
    assert out[ROOT_UNIT]['total_memory'] == G and out[ROOT_UNIT]['invalid_not_found'] == []
    CA.classify_root_named(out, ROOT_CAPS)


def test_root_named_script_never_raises_for_an_over_quota_unit(monkeypatch, capsys):
    out = run_root_named(monkeypatch, capsys, dict(system={ROOT_UNIT: loaded(cpu='1s')}))
    assert out[ROOT_UNIT]['total_cpu'] == pytest.approx(1.)
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_root_named(out, ROOT_CAPS)
    assert e.value.cls == 'owned_unit_over_quota'


@pytest.mark.parametrize('cpu,mem,field', [('infinity', str(G), 'total_cpu'), ('250xs', str(G), 'total_cpu'),
                                           ('250ms', 'infinity', 'total_memory'), ('250ms', '1.5', 'total_memory')])
def test_root_named_script_totals_are_null_when_unbounded_or_unparseable(monkeypatch, capsys, cpu, mem, field):
    out = run_root_named(monkeypatch, capsys, dict(system={ROOT_UNIT: loaded(cpu=cpu, mem=mem)}))
    assert out[ROOT_UNIT][field] is None
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_root_named(out, ROOT_CAPS)
    assert e.value.cls == 'owned_unit_over_quota'


@pytest.mark.parametrize('over', [dict(ActiveState='active'), dict(ControlGroup='/user.slice/x.scope'), dict(MainPID='7')])
def test_root_named_script_flags_an_invalid_not_found_row(monkeypatch, capsys, over):
    out = run_root_named(monkeypatch, capsys, dict(system={ROOT_UNIT: dict(NOT_FOUND, **over)}))
    assert out[ROOT_UNIT]['invalid_not_found'] == ['system']
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_root_named(out, ROOT_CAPS)
    assert e.value.cls == 'root_probe'


def test_root_named_script_has_no_assert_or_raise():
    tree = ast.parse(CA.ROOT_NAMED_SCRIPT.replace('UNITS', '{}'))
    assert [n for n in ast.walk(tree) if isinstance(n, (ast.Assert, ast.Raise))] == []


# --- native probe: the real NATIVE_SCRIPT text, run against a fake cgroup and proc tree ------------

NATIVE_NEEDLES = ("/sys/fs/cgroup/user.slice/user-'+str(os.getuid())+'.slice", "'/proc/meminfo'", "'/proc/pressure/cpu'")


def run_native_script(monkeypatch, capsys, tmp_path, memory_max):
    cg, meminfo, pressure = tmp_path/'cg', tmp_path/'meminfo', tmp_path/'pressure'
    cg.mkdir()
    (cg/'memory.max').write_text(memory_max + '\n')
    (cg/'memory.current').write_text(str(G) + '\n')
    (cg/'memory.stat').write_text('inactive_file 0\n')
    (cg/'io.pressure').write_text('full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
    meminfo.write_text('MemTotal: 16777216 kB\nMemAvailable: 8388608 kB\n')
    pressure.write_text('some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
    src = CA.NATIVE_SCRIPT
    for needle, value in zip(NATIVE_NEEDLES, (str(cg), repr(str(meminfo)), repr(str(pressure)))):
        assert src.count(needle) == 1, needle
        src = src.replace(needle, value)
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: '')
    exec(compile(src, 'native', 'exec'), {})
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize('memory_max,headroom', [('4294967296', 3*G), ('max', None)], ids=['numeric limit', 'systemd max'])
def test_native_script_reports_working_headroom_or_null(monkeypatch, capsys, tmp_path, memory_max, headroom):
    out = run_native_script(monkeypatch, capsys, tmp_path, memory_max)
    assert out['working_headroom'] == headroom
    assert out['physical_mem_available'] == 8*G and out['units'] == []


# --- evaluate -----------------------------------------------------------------------------------

def test_evaluate_passes_healthy_fixture_with_proof_fields():
    proof = healthy()
    for key in ('ledger_sha256', 'prospective_CPU', 'prospective_RAM', 'projected_root', 'pending', 'owned',
                'co_tenant_reserve', 'classes_checked'):
        assert key in proof
    assert proof['ledger_sha256'] == hashlib.sha256(json.dumps(ledger(), sort_keys=True).encode()).hexdigest()
    assert proof['co_tenant_reserve'] == dict(cpu=0., memory=0, units=[])


def test_evaluate_owned_unit_within_quota_passes():
    proof = healthy(ledger=ledger(OWN=owner_row()),
                    native=native(units=[dict(unit='workbay-lane-own-r3.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))]))
    assert proof['owned']['workbay-lane-own'][1] == G


def test_evaluate_one_small_bounded_co_tenant_passes_and_proof_shows_reserve():
    proof = healthy(native=native(units=[co('abc')]))
    assert proof['co_tenant_reserve'] == dict(cpu=1.0, memory=4294967296, units=['workbay-lane-other-abc.scope'])
    assert proof['prospective_CPU'] == pytest.approx(1.25 + 1.0 + 1.5)


REFUSALS = [
    ('setup owner', dict(ledger=ledger(setup_owner='Someone')), 'setup_owner'),
    ('pending reservations open', dict(ledger=ledger(pending_reservations_complete=False)), 'ledger_state'),
    ('expired owner lease', dict(ledger=ledger(WP=owner_row('wp', expires='2026-10-20T11:00:00+00:00'))), 'expired_owner_lease'),
    ('cpu pressure', dict(native=native(cpu='some avg10=60.00 avg60=60.00 avg300=0.00 total=0\n')), 'cpu_pressure'),
    ('io pressure', dict(native=native(io='full avg10=20.00 avg60=20.00 avg300=0.00 total=0\n')), 'io_pressure'),
    ('memory headroom', dict(native=native(avail=2*G)), 'memory_headroom'),
    ('disk projection', dict(root=root(pct='91%')), 'disk_projection'),
    ('root hits', dict(root=root(hits=['1234'])), 'root_probe'),
    ('ceiling exceeded without reserve', dict(profile=dict(aggregate_cpu_cores_max=3., aggregate_memory_bytes_max=2*G)), 'ledger_state'),
    ('two co-tenants over CPU ceiling', dict(native=native(units=[co('a', '1500ms'), co('b', '1500ms')])), 'co_tenant_reserve'),
    ('unbounded co-tenant', dict(native=native(units=[co('a', cpu='infinity')])), 'co_tenant_unbounded'),
    ('owned unit over quota', dict(ledger=ledger(OWN=owner_row()),
                                   native=native(units=[dict(unit='workbay-lane-own-r3.scope', CPUQuotaPerSecUSec='1s', MemoryMax=str(G))])),
     'owned_unit_over_quota'),
]


@pytest.mark.parametrize('label,over,cls', REFUSALS, ids=[r[0] for r in REFUSALS])
def test_evaluate_labels_each_refusal_class(label, over, cls):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(**over)
    assert e.value.cls == cls


# The projection is (used + pending) / (used + free). With the default ledger, pending is 3 GiB runtime + 1.4e9 B emergency
# (~1.30 GiB) + 1 GiB fixed + 4.5 GiB Aura term (no Aura_WP400_A key), about 9.80 GiB before any pending reservation.

def test_disk_projection_counts_a_pending_reservation():
    # (70 + 20 + 3 + 1.30 + 1 + 4.5) / 100 = 99.80% -> 100, over the 90% ceiling.
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(pending_reservations=[dict(reserved_bytes=20*G)]),
                root=root(pct='70%', used_kb=70*G//1024, free_kb=30*G//1024))
    assert e.value.cls == 'disk_projection' and 'projected 100%' in e.value.detail


def test_disk_projection_without_pending_reservations_is_admitted():
    # (70 + 3 + 1.30 + 1 + 4.5) / 100 = 79.80% -> 80, under the 90% ceiling.
    assert healthy(root=root(pct='70%', used_kb=70*G//1024, free_kb=30*G//1024))['projected_root'] == 80


def test_disk_projection_counts_the_fixed_reserves_and_the_aura_term():
    # (82 + 3 + 1.30 + 1 + 4.5) / 100 = 91.80% -> 92, over 90. Without the 4.5 Aura term it is (82 + 5.30) / 100 -> 88.
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(root=root(pct='82%', used_kb=82*G//1024, free_kb=18*G//1024))
    assert e.value.cls == 'disk_projection' and 'projected 92%' in e.value.detail


def wb_row(drop=(), **over):
    row = dict(remaining_actor_claim=1, cpu_cores_aggregate=.25, memory_bytes_aggregate=G, physical_key='wb-key',
               expires='2026-10-20T13:00:00+00:00', setup_granted=False)
    row.update(over)
    for field in drop:
        del row[field]
    return row


WB_VIOLATIONS = [
    ('negative cpu', dict(cpu_cores_aggregate=-3.0)),
    ('zero cpu', dict(cpu_cores_aggregate=0)),
    ('missing cpu', dict(drop=('cpu_cores_aggregate',))),
    ('missing memory', dict(drop=('memory_bytes_aggregate',))),
    ('missing physical key', dict(drop=('physical_key',))),
    ('missing expires', dict(drop=('expires',))),
    ('malformed expires', dict(expires='next tuesday')),
    ('naive expires', dict(expires='2026-10-20T13:00:00')),
]


@pytest.mark.parametrize('label,over', WB_VIOLATIONS, ids=[w[0] for w in WB_VIOLATIONS])
def test_wb_operations_row_is_checked_like_every_other_owner_row(label, over):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(WB_operations=dict(WB1=wb_row(**over))))
    assert e.value.cls == 'ledger_state'


def test_a_valid_wb_operations_row_is_admitted_and_its_unit_is_owned():
    proof = healthy(ledger=ledger(WB_operations=dict(WB1=wb_row())),
                    native=native(units=[dict(unit='workbay-lane-wb-key.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))]))
    assert proof['owned']['workbay-lane-wb-key'][1] == G


def test_a_wb_row_keyed_by_expected_physical_key_is_admitted():
    row = wb_row(drop=('physical_key',), expected_physical_key='wb-key')
    proof = healthy(ledger=ledger(WB_operations=dict(WB1=row)),
                    native=native(units=[dict(unit='workbay-lane-wb-key.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))]))
    assert proof['owned']['workbay-lane-wb-key'] == pytest.approx([.25, G])


def test_a_wb_operations_row_named_like_a_top_level_owner_row_is_refused_as_ledger_state():
    # The WB claim must carry valid bounds: a zero-resource claim is refused by require_bounds before the collision check.
    led = ledger(X=owner_row('x-key'), WB_operations=dict(X=wb_row(physical_key='wb-key')))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.owner_rows(led)
    assert e.value.cls == 'ledger_state' and 'owner row name collides with WB_operations: X' in e.value.detail


def test_an_owner_row_without_expires_is_a_labeled_refusal():
    row = owner_row()
    del row['expires']
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(OWN=row))
    assert e.value.cls == 'ledger_state'


def test_lane_memory_ceiling_is_named_for_its_lane_scope():
    assert CA.LANE_MEMORY_CEILING == 16*G and not hasattr(CA, 'MEMORY_CEILING')


def test_aura_runtime_reserve_is_named_for_aura_runtime():
    assert CA.AURA_RUNTIME_CPU == 1.5 and CA.AURA_RUNTIME_MEMORY == 4*G
    assert not hasattr(CA, 'GUEST_CPU') and not hasattr(CA, 'GUEST_MEMORY')


AURA = dict(active=True, cpu_cores_aggregate=1.5, memory_bytes_aggregate=4*G)


def test_active_aura_runtime_at_its_fixed_reserve_is_admitted():
    healthy(ledger=ledger(aura_runtime=AURA))


def test_active_aura_runtime_over_its_cpu_reserve_is_refused_as_ledger_state():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(aura_runtime=dict(AURA, cpu_cores_aggregate=1.75)))
    assert e.value.cls == 'ledger_state'


def test_active_aura_runtime_one_byte_over_its_memory_reserve_is_refused_as_ledger_state():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(aura_runtime=dict(AURA, memory_bytes_aggregate=4*G + 1)))
    assert e.value.cls == 'ledger_state'


def test_inactive_aura_runtime_is_not_bounded_by_the_reserve():
    healthy(ledger=ledger(aura_runtime=dict(AURA, active=False, cpu_cores_aggregate=3.)))


def test_wb_row_with_a_claim_and_cpu_is_refused_as_ledger_state():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(wb=dict(remaining_actor_claim=1, cpu_cores_aggregate=.5, memory_bytes_aggregate=0)))
    assert e.value.cls == 'ledger_state'


def test_wb_row_with_cpu_and_no_claim_is_admitted():
    healthy(ledger=ledger(wb=dict(remaining_actor_claim=0, cpu_cores_aggregate=.5, memory_bytes_aggregate=0)))


def test_wb_row_with_a_claim_and_zero_resources_is_admitted():
    healthy(ledger=ledger(wb=dict(remaining_actor_claim=1, cpu_cores_aggregate=0, memory_bytes_aggregate=0)))


def test_two_owner_rows_sharing_a_physical_key_are_refused_as_ledger_state():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(A=owner_row('dup-deadbeef'), B=owner_row('dup-deadbeef', cpu=1., mem=2*G)))
    assert e.value.cls == 'ledger_state' and 'duplicate unit key' in e.value.detail


def test_two_owner_rows_sharing_a_custody_unit_are_refused_as_ledger_state():
    a = dict(owner_row('a'), custody_unit='workbay-custody-x.scope')
    b = dict(owner_row('b'), custody_unit='workbay-custody-x.scope')
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(A=a, B=b))
    assert e.value.cls == 'ledger_state'


def test_one_row_naming_its_custody_unit_and_scope_alike_is_admitted():
    healthy(ledger=ledger(OWN=dict(owner_row(), custody_unit='workbay-custody-x.scope', custody_scope='workbay-custody-x.scope')))


def test_setup_granted_row_without_an_active_claim_is_refused_as_ledger_state():
    row = dict(setup_granted=True, aggregate_cpu_cores_max=2., aggregate_memory_bytes_max=8*G)
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(OWN=row))
    assert e.value.cls == 'ledger_state'


def test_row_without_setup_granted_or_a_claim_is_still_skipped():
    healthy(ledger=ledger(OWN=dict(setup_granted=False, aggregate_cpu_cores_max=2., aggregate_memory_bytes_max=8*G)))


OUTSIDE_OWNER_ROWS = [('remaining_actor_claim', 1), ('reserved_now', True), ('future_model_claims', 1),
                      ('aggregate_cpu_cores_max', .5), ('aggregate_memory_bytes_max', G)]


@pytest.mark.parametrize('field,value', OUTSIDE_OWNER_ROWS, ids=[f for f, _ in OUTSIDE_OWNER_ROWS])
@pytest.mark.parametrize('name', ['aura', 'Canvas'])
def test_aura_and_canvas_holding_a_claim_or_reservation_are_refused_as_ledger_state(name, field, value):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(**{name: dict(active_models=[], setup_granted=False, **{field: value})}))
    assert e.value.cls == 'ledger_state'
    assert e.value.detail == f'{name} holds a claim or reservation outside owner_rows'


def test_aura_and_canvas_at_their_live_no_claim_shape_are_admitted():
    healthy(ledger=ledger(aura=dict(active_models=[], setup_granted=False, remaining_actor_claim=None, reserved_now=None,
                                    future_model_claims=None, aggregate_cpu_cores_max=None, aggregate_memory_bytes_max=None),
                          Canvas=dict(active_models=[], setup_granted=False, future_model_claims=0,
                                      aggregate_cpu_cores_max=0, aggregate_memory_bytes_max=0)))


def test_wb_row_with_setup_granted_and_no_claim_is_refused_as_ledger_state():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(WB_operations=dict(WB1=wb_row(remaining_actor_claim=0, setup_granted=True))))
    assert e.value.cls == 'ledger_state' and e.value.detail == 'setup granted: WB1'


def test_wb_row_with_no_claim_and_no_setup_is_still_skipped():
    healthy(ledger=ledger(WB_operations=dict(WB1=wb_row(remaining_actor_claim=0))))


# The lane total is 2 GiB (coordinator) + the profile + 4 GiB (no Aura row yet), so 10 GiB of profile is exactly the ceiling.
AT_MEMORY_CEILING = dict(aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=10*G)


def test_lane_memory_exactly_at_the_ceiling_is_admitted():
    healthy(profile=AT_MEMORY_CEILING)


def test_lane_memory_one_byte_over_the_ceiling_is_refused_as_ledger_state():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(profile=dict(AT_MEMORY_CEILING, aggregate_memory_bytes_max=10*G + 1))
    assert e.value.cls == 'ledger_state'


def test_lane_memory_at_the_ceiling_with_a_co_tenant_is_refused_as_co_tenant_reserve():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(profile=AT_MEMORY_CEILING, native=native(units=[co('abc', cpu='250ms', mem=str(G))]))
    assert e.value.cls == 'co_tenant_reserve'


def test_headroom_of_none_uses_physical_memory_alone():
    healthy(native=native(headroom=None))


def test_headroom_of_none_still_refuses_low_physical_memory():
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(native=native(headroom=None, avail=2*G))
    assert e.value.cls == 'memory_headroom'


def test_plain_ceiling_refusal_is_not_masked_by_an_earlier_reserved_one():
    # cpu is 2.75 here: the CPU ceiling fails only with the 0.75-core co-tenant, but the host CPU check fails
    # without it (2.75 + 1.5 > 4), so the deterministic ledger_state must win and admit must not retry.
    over = dict(profile=dict(aggregate_cpu_cores_max=2., aggregate_memory_bytes_max=2*G), native=native(units=[co('a', '750ms')]))
    attempts, slept = [], []

    def attempt():
        attempts.append(1)
        return healthy(**over)
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.admit(attempt, sleep=slept.append)
    assert e.value.cls == 'ledger_state'
    assert len(attempts) == 1 and slept == []


MALFORMED_AVG60 = ['avg60=0garbage', 'avg60=.', 'avg60=1..2', 'avg60=nan', 'avg60=inf', 'avg60=-1']


@pytest.mark.parametrize('token', MALFORMED_AVG60)
def test_cpu_pressure_refuses_a_malformed_avg60(token):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(native=native(cpu=f'some avg10=0.00 {token} avg300=0.00 total=0\n'))
    assert e.value.cls == 'cpu_pressure'


@pytest.mark.parametrize('token', MALFORMED_AVG60)
def test_io_pressure_refuses_a_malformed_avg60(token):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(native=native(io=f'full avg10=0.00 {token} avg300=0.00 total=0\n'))
    assert e.value.cls == 'io_pressure'


@pytest.mark.parametrize('text', ['full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n', ''])
def test_cpu_pressure_refuses_an_absent_row(text):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(native=native(cpu=text))
    assert e.value.cls == 'cpu_pressure'


@pytest.mark.parametrize('text', ['some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n', ''])
def test_io_pressure_refuses_an_absent_row(text):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(native=native(io=text))
    assert e.value.cls == 'io_pressure'


# --- admit --------------------------------------------------------------------------------------

def scripted(*outcomes):
    calls = []

    def attempt():
        calls.append(1)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out
    return attempt, calls


def test_admit_retries_transient_refusals_then_succeeds():
    attempt, calls = scripted(refusal('cpu_pressure'), refusal('io_pressure'), 'ok')
    slept = []
    assert CA.admit(attempt, sleep=slept.append) == 'ok'
    assert len(calls) == 3 and slept == [60, 60]


def test_admit_stops_after_one_deterministic_refusal():
    attempt, calls = scripted(refusal('setup_owner'))
    slept = []
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.admit(attempt, sleep=slept.append)
    assert e.value.cls == 'setup_owner'
    assert len(calls) == 1 and slept == []


def test_admit_exhausts_bounded_transient_attempts_with_labeled_refusal():
    attempt, calls = scripted(*[refusal('cpu_pressure') for _ in range(6)])
    slept = []
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.admit(attempt, sleep=slept.append)
    assert 'exhausted after 6 attempts' in str(e.value)
    assert e.value.cls == 'cpu_pressure' and e.value.transient
    assert len(calls) == 6 and len(slept) == 5


def test_admit_propagates_non_refusal_exceptions_unchanged():
    attempt, calls = scripted(RuntimeError('boom'))
    with pytest.raises(RuntimeError, match='boom'):
        CA.admit(attempt, sleep=lambda s: None)
    assert len(calls) == 1


# --- guard (IO shape, with r6 faked; no ssh) ----------------------------------------------------

def fake_r6(monkeypatch, tmp_path, led):
    (tmp_path/'raw_auth_source_gate_root_probe.py').write_text('print(1)\n')
    persisted = []
    fake = types.ModuleType('run_owner_root_fixture_r6')
    def persist(path, obj):
        path.write_text(json.dumps(obj))
        persisted.append((path, obj))
    fake.cap = types.SimpleNamespace(LEDGER=led, persist=persist)
    fake.P, fake.N, fake.PROFILE = tmp_path, 'QWEN-TEST', PROFILE
    fake.d = types.SimpleNamespace(HOST='native-host')
    monkeypatch.setitem(sys.modules, 'run_owner_root_fixture_r6', fake)
    return persisted


def probe_argv(host):
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, 'sudo -n python3 -' if host.startswith('ubuntu@') else 'python3 -']


def ssh_reply(obj=None, rc=0, stdout=None, stderr=''):
    return types.SimpleNamespace(returncode=rc, stdout=json.dumps(obj) if stdout is None else stdout, stderr=stderr)


def fake_ssh(monkeypatch, handle):
    """Stands in for subprocess.run. handle(argv, script) returns a reply, or an exception to raise; every call is recorded."""
    calls = []

    def run(argv, input=None, capture_output=None, text=None, timeout=None):
        calls.append(dict(argv=argv, script=input, timeout=timeout))
        out = handle(argv, input)
        if isinstance(out, BaseException):
            raise out
        return out
    monkeypatch.setattr(subprocess, 'run', run)
    return calls


def in_order(*outs):
    it = iter(outs)
    return lambda argv, script: next(it)


def test_guard_probes_then_delegates_to_evaluate(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger()))
    persisted = fake_r6(monkeypatch, tmp_path, led)
    calls = fake_ssh(monkeypatch, lambda argv, script: ssh_reply(native() if argv[5] == 'native-host' else root()))
    before, got, proof = CA.guard()
    assert before == led.read_bytes() and got == ledger()
    assert persisted == [(tmp_path/'QWEN-TEST.operation-capacity.json', proof)]
    assert proof['root']['euid'] == 0 and proof['native']['units'] == []
    assert [(c['argv'], c['timeout']) for c in calls] == [(probe_argv(CA.HOST), 30), (probe_argv('native-host'), 30)]


def test_guard_refuses_when_ledger_changes_during_probe(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger()))

    def handle(argv, script):
        if argv[5] == 'native-host':
            led.write_text(json.dumps(ledger(note='moved')))
            return ssh_reply(native())
        return ssh_reply(root())
    fake_r6(monkeypatch, tmp_path, led)
    fake_ssh(monkeypatch, handle)
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'ledger_state'


def test_guard_refuses_an_owned_unit_over_quota_before_evaluating(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger(OWN=dict(owner_row(), native_unit=ROOT_UNIT))))
    probe = dict(system=dict(LoadState='loaded'), total_cpu=1., total_memory=G, invalid_not_found=[])

    def handle(argv, script):
        if argv[5] == CA.HOST and 'LoadState' in script:
            return ssh_reply({ROOT_UNIT: probe})
        return ssh_reply(native() if argv[5] == 'native-host' else root())
    persisted = fake_r6(monkeypatch, tmp_path, led)
    fake_ssh(monkeypatch, handle)
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'owned_unit_over_quota'
    assert persisted == []


def test_guard_labels_a_probe_transport_failure_as_transient(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger()))
    persisted = fake_r6(monkeypatch, tmp_path, led)
    fake_ssh(monkeypatch, lambda argv, script: subprocess.TimeoutExpired(argv, 30))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'probe_transport' and e.value.transient
    assert persisted == []


def test_guard_refuses_two_owner_rows_sharing_a_native_unit_before_any_probe(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger(A=dict(owner_row('a'), native_unit=ROOT_UNIT), B=dict(owner_row('b'), native_unit=ROOT_UNIT))))
    persisted = fake_r6(monkeypatch, tmp_path, led)
    calls = fake_ssh(monkeypatch, lambda argv, script: ssh_reply(root()))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'ledger_state' and e.value.detail == 'duplicate native unit across owner rows: B'
    assert calls == [] and persisted == []


def test_native_units_keeps_each_distinct_unit_with_its_own_cap():
    rows = dict(A=dict(native_unit='u1', aggregate_cpu_cores_max=.25, aggregate_memory_bytes_max=G),
                B=dict(native_unit='u2', aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=2*G),
                C=dict(aggregate_cpu_cores_max=.5, aggregate_memory_bytes_max=G))
    assert CA.native_units(rows) == {'u1': [.25, G], 'u2': [.5, 2*G]}


def guard_under(monkeypatch, tmp_path, ledger_text=None, root_reply=None, native_reply=None):
    """Sets up CA.guard() over fakes: the ledger text and each probe's reply. Unset arguments are the healthy fixture."""
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger()) if ledger_text is None else ledger_text)
    fake_r6(monkeypatch, tmp_path, led)
    replies = dict(root=root() if root_reply is None else root_reply, native=native() if native_reply is None else native_reply)
    fake_ssh(monkeypatch, lambda argv, script: ssh_reply(replies['native' if argv[5] == 'native-host' else 'root']))


def without(mapping, key):
    return {k: v for k, v in mapping.items() if k != key}


MALFORMED = {
    'ledger without WB_operations': dict(ledger_text=json.dumps(without(ledger(), 'WB_operations'))),
    'ledger that is not JSON': dict(ledger_text='{"Bakeoff": '),
    'ledger without a top-level key': dict(ledger_text=json.dumps(without(ledger(), 'Bakeoff'))),
    'df reply with one line': dict(root_reply=dict(root(), df='Filesystem 1K-blocks Used Available Use% Mounted on\n')),
    'root probe without euid': dict(root_reply=without(root(), 'euid')),
    'native reply without physical_mem_available': dict(native_reply=without(native(), 'physical_mem_available')),
}


@pytest.mark.parametrize('label', list(MALFORMED), ids=list(MALFORMED))
def test_malformed_payload_is_a_labeled_deterministic_refusal(tmp_path, monkeypatch, label):
    guard_under(monkeypatch, tmp_path, **MALFORMED[label])
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'malformed_payload' and not e.value.transient


def test_guard_persists_no_proof_when_the_ledger_changed_during_the_probe(tmp_path, monkeypatch):
    reads = iter([json.dumps(ledger()).encode(), json.dumps(ledger(note='moved')).encode()])
    fake_r6(monkeypatch, tmp_path, types.SimpleNamespace(read_bytes=lambda: next(reads)))
    fake_ssh(monkeypatch, lambda argv, script: ssh_reply(native() if argv[5] == 'native-host' else root()))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'ledger_state'
    assert not (tmp_path/'QWEN-TEST.operation-capacity.json').exists()


# --- ssh_json: transport failures are transient, a probe that ran and failed or replied badly is deterministic ---

@pytest.mark.parametrize('exc', [subprocess.TimeoutExpired(['ssh'], 30), OSError('no ssh binary')], ids=['timeout', 'oserror'])
def test_ssh_json_timeout_and_oserror_are_transient_probe_transport(monkeypatch, exc):
    fake_ssh(monkeypatch, lambda argv, script: exc)
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.ssh_json(probe_argv(CA.HOST), 'x', 30)
    assert e.value.cls == 'probe_transport' and e.value.transient


def test_ssh_json_exit_255_is_ssh_own_failure_and_transient(monkeypatch):
    fake_ssh(monkeypatch, lambda argv, script: ssh_reply(rc=255, stdout='', stderr='Connection timed out'))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.ssh_json(probe_argv(CA.HOST), 'x', 30)
    assert e.value.cls == 'probe_transport' and e.value.transient


def test_ssh_json_other_nonzero_exit_is_deterministic_root_probe_with_stderr(monkeypatch):
    fake_ssh(monkeypatch, lambda argv, script: ssh_reply(rc=1, stdout='', stderr='sudo: a password is required'))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.ssh_json(probe_argv(CA.HOST), 'x', 30)
    assert e.value.cls == 'root_probe' and not e.value.transient
    assert 'a password is required' in e.value.detail


@pytest.mark.parametrize('stdout', ['not json', '', '[1, 2]'], ids=['text', 'empty', 'not an object'])
def test_ssh_json_malformed_reply_is_deterministic_root_probe(monkeypatch, stdout):
    fake_ssh(monkeypatch, lambda argv, script: ssh_reply(stdout=stdout))
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.ssh_json(probe_argv(CA.HOST), 'x', 30)
    assert e.value.cls == 'root_probe' and not e.value.transient


def test_ssh_json_passes_the_script_on_stdin_and_returns_the_object(monkeypatch):
    calls = fake_ssh(monkeypatch, lambda argv, script: ssh_reply(dict(ok=1)))
    assert CA.ssh_json(probe_argv('native-host'), 'print(1)', 30) == dict(ok=1)
    assert calls == [dict(argv=probe_argv('native-host'), script='print(1)', timeout=30)]


def test_admit_retries_one_transport_failure_then_returns_the_probe(monkeypatch):
    fake_ssh(monkeypatch, in_order(subprocess.TimeoutExpired(['ssh'], 30), ssh_reply(dict(ok=1))))
    slept = []
    assert CA.admit(lambda: CA.ssh_json(probe_argv(CA.HOST), 'x', 30), attempts=2, sleep=slept.append) == dict(ok=1)
    assert slept == [60]


def test_admit_stops_after_one_deterministic_probe_refusal(monkeypatch):
    calls = fake_ssh(monkeypatch, in_order(ssh_reply(rc=1, stdout='', stderr='boom')))
    slept = []
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.admit(lambda: CA.ssh_json(probe_argv(CA.HOST), 'x', 30), attempts=6, sleep=slept.append)
    assert e.value.cls == 'root_probe'
    assert len(calls) == 1 and slept == []


# --- runner v2: CLI -----------------------------------------------------------------------------

def test_previous_settlement_is_rejected_by_the_cli_with_exit_2():
    r = subprocess.run([sys.executable, '-I', '-B', str(QWEN_AB/'run_qwen_cohort_operation.py'), '--name', 'n',
                        '--dir', str(QWEN_AB), '--gate-commit', 'g', '--previous-settlement', 'x'],
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_parse_args_accepts_the_v2_flags():
    a = RUN.parse_args(['--name', 'n', '--dir', 'd', '--gate-commit', 'g'])
    assert (a.name, a.dir, a.gate_commit, a.pilot) == ('n', 'd', 'g', None)


# --- runner v2: verify_prepared -----------------------------------------------------------------

SHA = 'ab94e904ca25e2e031ad241f2600aa0406201c15'
ROOT = '/home/gate/bakeoff-rounds-20261017-inputs/source'
WORKSPACE = '/home/gate/bakeoff-rounds-20261017-inputs/results/n-1/workspace'
BINDING = dict(source=SHA, repo=f'{ROOT}/{SHA}', python=f'{ROOT}/{SHA}.venv/bin/python', workspace=WORKSPACE)
RECIPE = (f"window=Path('/tmp/qwen-owner-window.abc123')\nSOURCE='{SHA}'\n"
          f"repo=Path('{ROOT}')/SOURCE\npython=repo.parent/(SOURCE+'.venv')/'bin/python'\n"
          f"workspace=Path('{WORKSPACE}');x=1\nx = 1\n").encode()
SRC = b'print("preparer")\n'


def prepared(raw=RECIPE, **extra):
    base = dict(recipe_sha256=hashlib.sha256(raw).hexdigest(), predecessor_binding='late_bound_at_claim_refresh',
                mode='full', preparer_sha256=hashlib.sha256(SRC).hexdigest())
    base.update(extra)
    return base


def test_verify_prepared_returns_the_window_on_success():
    assert RUN.verify_prepared(prepared(), RECIPE) == '/tmp/qwen-owner-window.abc123'


def test_verify_prepared_rejects_a_sha_mismatch():
    with pytest.raises(ValueError):
        RUN.verify_prepared(prepared(), RECIPE + b'#')


def test_verify_prepared_rejects_a_recipe_that_does_not_parse():
    raw = b"window=Path('/tmp/qwen-owner-window.abc123')\ndef (:\n"
    with pytest.raises(ValueError):
        RUN.verify_prepared(prepared(raw), raw)


def test_verify_prepared_requires_late_bound_predecessor():
    p = prepared()
    del p['predecessor_binding']
    with pytest.raises(ValueError, match='late_bound'):
        RUN.verify_prepared(p, RECIPE)


def test_verify_prepared_rejects_a_pinned_actual_previous_auto():
    with pytest.raises(ValueError, match='actual_previous_AUTO'):
        RUN.verify_prepared(prepared(actual_previous_AUTO='op-1'), RECIPE)


def test_verify_prepared_rejects_unknown_mode():
    with pytest.raises(ValueError):
        RUN.verify_prepared(prepared(mode='dry'), RECIPE)


@pytest.mark.parametrize('raw', [b'x = 1\n', RECIPE + RECIPE])
def test_verify_prepared_requires_exactly_one_window_line(raw):
    with pytest.raises(ValueError, match='window'):
        RUN.verify_prepared(prepared(raw), raw)


# --- runner v3: source_binding ------------------------------------------------------------------

SOURCE_LINE = f"SOURCE='{SHA}'".encode()
REPO_LINE = f"repo=Path('{ROOT}')/SOURCE".encode()
PYTHON_LINE = b"python=repo.parent/(SOURCE+'.venv')/'bin/python'"
WORKSPACE_LINE = f"workspace=Path('{WORKSPACE}')".encode()


def swapped(old, new):
    assert RECIPE.count(old) == 1, old
    return RECIPE.replace(old, new)


def test_source_binding_accepts_the_fixture_and_returns_the_four_exact_paths():
    assert RUN.source_binding(RECIPE) == BINDING


@pytest.mark.parametrize('raw,message', [
    (swapped(REPO_LINE, b"repo=Path('/home/gate/workbay-sandbox')/SOURCE"), 'recipe binds a reaped WorkBay lane sandbox'),
    (RECIPE + b"x='.venv-lane-'\n", 'recipe binds a reaped lane venv (.venv-lane-)'),
    (RECIPE + REPO_LINE + b'\n', 'repo line must appear exactly once, found 2'),
    (RECIPE.replace(PYTHON_LINE + b'\n', b''), 'python line must appear exactly once, found 0'),
    (swapped(SOURCE_LINE, b"SOURCE='ab94e904'"), 'SOURCE line must appear exactly once, found 0'),
    (swapped(WORKSPACE_LINE, b"workspace=Path('/tmp/n-1/workspace')"), 'workspace line must appear exactly once, found 0'),
])
def test_source_binding_refuses_each_unbound_recipe_with_its_message(raw, message):
    with pytest.raises(ValueError) as e:
        RUN.source_binding(raw)
    assert str(e.value) == message


RESULTS = '/home/gate/bakeoff-rounds-20261017-inputs/results'
# QDSG1-01: a second binding of a bound name, anywhere in the module, is refused even when the text checks each see exactly one line.
REBINDS = [
    pytest.param(swapped(WORKSPACE_LINE, WORKSPACE_LINE + b";workspace=Path('/tmp/unchecked-workspace')"), 'workspace', id='same-line'),
    pytest.param(RECIPE + b"workspace=Path('/tmp/unchecked-workspace')\n", 'workspace', id='later-line'),
    pytest.param(RECIPE + b"for workspace in ['/tmp/unchecked']:\n    pass\n", 'workspace', id='for-target'),
    pytest.param(RECIPE + b'import os as workspace\n', 'workspace', id='import-as'),
    pytest.param(RECIPE + b'def repo():\n    pass\n', 'repo', id='def'),
    pytest.param(RECIPE + b'class python:\n    pass\n', 'python', id='class'),
    pytest.param(RECIPE + b"python += 'x'\n", 'python', id='augassign'),
    pytest.param(RECIPE + b'f = lambda SOURCE: 0\n', 'SOURCE', id='lambda-arg'),
    pytest.param(RECIPE + b'def f():\n    global SOURCE\n', 'SOURCE', id='global'),
    pytest.param(RECIPE + b'try:\n    pass\nexcept Exception as repo:\n    pass\n', 'repo', id='except-as'),
]


@pytest.mark.parametrize('raw,name', REBINDS)
def test_source_binding_refuses_any_second_binding_of_a_bound_name(raw, name):
    with pytest.raises(ValueError) as e:
        RUN.source_binding(raw)
    assert str(e.value) == f'{name} must be bound exactly once, found 2 bindings'


def test_source_binding_refuses_a_sha_line_that_only_sits_inside_a_string():
    raw = swapped(SOURCE_LINE, b'"""\n' + SOURCE_LINE + b'\n"""')
    with pytest.raises(ValueError) as e:
        RUN.source_binding(raw)
    assert str(e.value) == 'SOURCE must be bound exactly once, found 0 bindings'


def test_source_binding_refuses_a_bound_name_that_is_not_a_module_level_assignment():
    # The repo line survives only inside a string, and the one real binding of repo is a for target: the text check sees one line, the module has one binding that is not an assignment.
    raw = swapped(REPO_LINE, b'"""\n' + REPO_LINE + b'\n"""\nfor repo in []:\n    pass')
    with pytest.raises(ValueError) as e:
        RUN.source_binding(raw)
    assert str(e.value) == 'repo is bound outside a module-level single-target assignment, found 1 binding'


def test_source_binding_refuses_a_star_import_that_could_rebind_any_name():
    with pytest.raises(ValueError) as e:
        RUN.source_binding(RECIPE + b'from os.path import *\n')
    assert str(e.value) == 'recipe imports * and could rebind a bound name'


def test_source_binding_refuses_a_recipe_that_does_not_parse():
    with pytest.raises(ValueError, match='^recipe does not parse'):
        RUN.source_binding(RECIPE + b'def (:\n')


# QDSG1-02: the workspace is exactly <results root>/<NAME>/workspace; '..', '.', '//' and a trailing slash are refused, not normalised.
@pytest.mark.parametrize('tail', ['../workspace', './workspace', 'a/../b/workspace', '/x/workspace', 'n-1/workspace/',
                                  '.hidden/workspace', 'n-1/ws'])
def test_source_binding_refuses_a_workspace_that_is_not_a_direct_child_of_results(tail):
    bad = f'{RESULTS}/{tail}'
    raw = swapped(WORKSPACE_LINE, f"workspace=Path('{bad}')".encode())
    with pytest.raises(ValueError) as e:
        RUN.source_binding(raw)
    assert str(e.value) == f'workspace must be {RESULTS}/<NAME>/workspace, got {bad!r}'


@pytest.mark.parametrize('name', ['n-1', 'a.b_c-9', 'A'])
def test_source_binding_accepts_each_well_formed_result_name(name):
    workspace = f'{RESULTS}/{name}/workspace'
    assert RUN.source_binding(swapped(WORKSPACE_LINE, f"workspace=Path('{workspace}')".encode()))['workspace'] == workspace


# --- runner v2: bind_generator ------------------------------------------------------------------

class FakeGit:
    def __init__(self, ancestor=True, src=SRC):
        self.ancestor, self.src, self.calls = ancestor, src, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == 'merge-base':
            if not self.ancestor:
                raise subprocess.CalledProcessError(1, ['git', *args])
            return b''
        return self.src


def test_bind_generator_accepts_the_generator_landed_at_the_gate():
    git = FakeGit()
    RUN.bind_generator(prepared(), 'gate1', git)
    assert git.calls[0] == ('merge-base', '--is-ancestor', 'gate1', 'main')
    assert git.calls[1] == ('show', 'gate1:.task-state/bakeoff-rounds-20261017/qwen-ab/workspace/prepare_qwen_ab.py')


def test_bind_generator_rejects_a_gate_that_is_not_on_main():
    with pytest.raises(ValueError):
        RUN.bind_generator(prepared(), 'gate1', FakeGit(ancestor=False))


def test_bind_generator_rejects_a_sha_mismatch():
    with pytest.raises(ValueError):
        RUN.bind_generator(prepared(), 'gate1', FakeGit(src=b'other\n'))


# --- runner v2: main wiring, with ssh, git, the shared runner and admission all stubbed ----------

RUNNER_NAME = 'run_selected_root_resume_qualification'
LEAVES = ('run_owner_root_fixture_r6', 'bakeoff_frontier_capacity', 'orchestrate')
RUNNER_REF = QWEN_AB/'references'/'admission'/(RUNNER_NAME + '.py')
HELPER_REF = QWEN_AB/'references'/'LEXICON-MIMO-40-LAST40-R1.prepared.json'


def operator_bakeoff(bakeoff, runner_bytes):
    """The operator's BAKEOFF: the untracked runner and its two untracked leaves, plus r6. Preflight locates these files; it never runs them."""
    bakeoff.mkdir(exist_ok=True)
    (bakeoff/(RUNNER_NAME + '.py')).write_bytes(runner_bytes)
    for name in LEAVES:
        (bakeoff/(name + '.py')).write_text(f'# stand-in {name}: located by find_spec, never executed by the preflight\n')


def one_byte_changed(raw):
    return bytes([raw[0] ^ 1]) + raw[1:]


def run_fixture(tmp_path):
    d = tmp_path/'dir'
    d.mkdir()
    (d/'n.prepared.json').write_text(json.dumps(prepared(RECIPE, name='n', mode='pilot', candidate='qwen', unit='workbay-x.scope',
                                                          gate_token='tok', preparer_sha256=hashlib.sha256(SRC).hexdigest())))
    (d/'n.remote.py').write_bytes(RECIPE)
    (d/'LEXICON-MIMO-40-LAST40-R1.prepared.json').write_bytes(HELPER_REF.read_bytes())
    payload = json.dumps(dict(status='PASS', source_sha=CUSTODY_SOURCE)).encode()
    with tarfile.open(d/'QWEN-AB-G2.custody.tar', 'w') as t:
        info = tarfile.TarInfo('output/result.json')
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    bakeoff = tmp_path/'bakeoff'
    operator_bakeoff(bakeoff, RUNNER_REF.read_bytes())
    (bakeoff/'QWEN-AB-G2.actual-capacity-return.json').write_text(json.dumps(dict(remaining_actor_claim=0)))
    return d, bakeoff


@pytest.fixture
def operator_checkout(tmp_path, monkeypatch):
    """The lane's inputs with BAKEOFF at the operator copy. No runner is in sys.modules, so the preflight must find it on disk."""
    d, bakeoff = run_fixture(tmp_path)
    monkeypatch.setattr(RUN, 'BAKEOFF', bakeoff)
    monkeypatch.setattr(RUN, 'run_git', FakeGit())
    monkeypatch.setattr(sys, 'path', list(sys.path))
    for name in (RUNNER_NAME,) + LEAVES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    argv = ['--name', 'n', '--dir', str(d), '--gate-commit', 'g1']
    return dict(d=d, bakeoff=bakeoff, argv=argv, monkeypatch=monkeypatch)


@pytest.fixture
def stubbed_main(operator_checkout, monkeypatch, tmp_path):
    m = operator_checkout
    monkeypatch.setattr(RUN.subprocess, 'run', lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(report()), stderr=''))
    persisted, runs = [], []
    fake_runner = types.ModuleType(RUNNER_NAME)
    # The preflight reads the spec's origin and checks its bytes, so the stand-in is located at the operator copy.
    fake_runner.__spec__ = importlib.util.spec_from_file_location(RUNNER_NAME, m['bakeoff']/(RUNNER_NAME + '.py'))
    fake_runner.admission = types.SimpleNamespace(guard=None, N=None, PROFILE=None)
    fake_runner.cap = types.SimpleNamespace(persist=lambda path, obj: persisted.append((path, obj)))
    results, terminal = tmp_path/'results', dict(exit_code=0)
    results.mkdir()
    def run(head, gate):
        runs.append((head, gate))
        # The shared runner writes its terminal record before it returns; main reads the remote exit code from it.
        (results/(fake_runner.N + '.transport-terminal.json')).write_text(json.dumps(terminal))
    fake_runner.P = results
    fake_runner.run = run
    monkeypatch.setitem(sys.modules, RUNNER_NAME, fake_runner)
    return dict(m, runner=fake_runner, persisted=persisted, runs=runs, terminal=terminal)


def test_main_admits_then_runs_with_cohort_identity_and_bootstrap(stubbed_main):
    m, admitted = stubbed_main, []
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: admitted.append(1))
    assert RUN.main(m['argv']) == 0
    runner = m['runner']
    assert admitted == [1] and m['runs'] == [(CUSTODY_SOURCE, 'QWEN-AB-G2')]
    assert runner.admission.guard is CA.guard
    assert (runner.N, runner.UNIT) == ('n', 'workbay-x.scope')
    assert runner.ROLE == 'actual_frozen_Qwen_qwen_paired_lexicon_pilot_cohort'
    assert runner.admission.N == 'n' and runner.admission.PROFILE['native_unit'] == 'workbay-x.scope'
    assert (m['bakeoff']/'n.preclaim.json') in [p for p, _ in m['persisted']]
    files, receipt = runner.inputs(CUSTODY_SOURCE, 'QWEN-AB-G2')
    assert (m['bakeoff']/'n.remote.py').read_bytes() == RECIPE
    assert files == {} and receipt['gate_commit'] == 'g1'
    assert receipt['predecessor_binding'] == 'late_bound_at_claim_refresh'
    assert receipt['preclaim']['publication']['action'] == 'auto'
    source = runner.bootstrap({}, receipt)
    assert 'tok' in source and 'QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256' not in source


@pytest.mark.parametrize('cls,code', [('cpu_pressure', 75), ('setup_owner', 3), ('owned_unit_over_quota', 3)])
def test_main_maps_admission_refusal_to_exit_code_without_running(stubbed_main, cls, code, capsys):
    def refuse(*a, **k):
        raise CA.AdmissionRefusal(cls, 'x')
    stubbed_main['monkeypatch'].setattr(CA, 'admit', refuse)
    assert RUN.main(stubbed_main['argv']) == code
    assert stubbed_main['runs'] == []
    status = json.loads(capsys.readouterr().out)
    assert status == dict(status='ADMISSION_REFUSED', refusal=f'refusal:{cls}: x', transient=code == 75)


def times_out(argv, **kwargs):
    raise subprocess.TimeoutExpired(argv, kwargs['timeout'])


def test_main_preclaim_transport_failure_exits_75_without_running(stubbed_main, capsys):
    m = stubbed_main
    m['monkeypatch'].setattr(RUN.subprocess, 'run', times_out)
    assert RUN.main(m['argv']) == 75
    assert m['runs'] == []
    status = json.loads(capsys.readouterr().out)
    assert status['status'] == 'ADMISSION_REFUSED' and status['refusal'].startswith('refusal:probe_transport:')
    assert status['transient'] is True


def test_main_malformed_preclaim_reply_exits_3_without_running(stubbed_main, capsys):
    m = stubbed_main
    m['monkeypatch'].setattr(RUN.subprocess, 'run', lambda *a, **k: types.SimpleNamespace(returncode=0, stdout='{"gpu": ', stderr=''))
    assert RUN.main(m['argv']) == 3
    assert m['runs'] == []
    status = json.loads(capsys.readouterr().out)
    assert status['refusal'].startswith('refusal:root_probe:') and status['transient'] is False


def test_main_preclaim_probe_is_run_with_the_ssh_argv_and_timeout(stubbed_main):
    m = stubbed_main
    seen = []
    m['monkeypatch'].setattr(RUN.subprocess, 'run', lambda argv, **k: seen.append((argv, k['timeout'])) or
                             types.SimpleNamespace(returncode=0, stdout=json.dumps(report()), stderr=''))
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: None)
    RUN.main(m['argv'])
    assert seen == [(['ssh', '-oBatchMode=yes', RUN.HOST, 'sudo -n /usr/bin/python3 -I -B -'], 30)]


def test_main_refuses_a_prepared_record_bound_to_another_name(stubbed_main):
    m = stubbed_main
    for p in m['d'].glob('n.*'):
        (m['d']/p.name.replace('n.', 'alias.', 1)).write_bytes(p.read_bytes())
    calls = []
    m['monkeypatch'].setattr(RUN.subprocess, 'run', lambda *a, **k: calls.append(('run', a)))
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: calls.append(('admit', a)))
    with pytest.raises(SystemExit, match='preflight refused'):
        RUN.main(['--name', 'alias', '--dir', str(m['d']), '--gate-commit', 'g1'])
    assert calls == [] and m['persisted'] == [] and m['runs'] == []


@pytest.mark.parametrize('rc', [1, 255])
def test_main_reports_a_failed_remote_transport_as_exit_4(stubbed_main, capsys, rc):
    m = stubbed_main
    m['terminal']['exit_code'] = rc
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: None)
    assert RUN.main(m['argv']) == 4
    assert json.loads(capsys.readouterr().out) == dict(status='ROOT_TRANSPORT_FAILED', exit_code=rc)


def test_main_lets_a_missing_terminal_record_raise(stubbed_main):
    m = stubbed_main
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: None)
    m['runner'].run = lambda head, gate: None
    with pytest.raises(FileNotFoundError):
        RUN.main(m['argv'])


# --- runner v2: pilot checks, with the frozen keys that the pilot and the full recipe must share ---

FROZEN = dict(candidate='qwen', asset_spec_sha256='a' * 64, model_contract=dict(wire_model_id='wire-1', model_revision='rev-1'),
              sources=['src-1'], immutable_candidate_configs=dict(cfg='c1'))
FULL = dict(FROZEN, mode='full', preparer_sha256=hashlib.sha256(SRC).hexdigest())
PILOT = dict(FROZEN, mode='pilot', predecessor_binding='late_bound_at_claim_refresh', preparer_sha256=hashlib.sha256(SRC).hexdigest())
PILOT_CAPACITY = dict(remaining_actor_claim=0, native=dict(GPU_stopped=True, UID0_hits=0, UID0_errors=0),
                      execution_evidence=dict(persisted_image_rows=2, contract_valid_pairs=2, recorded_completion_POST_attempts=6))
PILOT_RESULT = dict(complete=True, evaluated_images=2, item_errors=0, raw_passes=6)
PILOT_RAW = dict(model_id='wire-1', model_revision='rev-1', valid_pairs=2)
PILOT_VIOLATIONS = {
    'remaining_actor_claim=1': dict(capacity=dict(PILOT_CAPACITY, remaining_actor_claim=1)),
    'GPU_stopped=False': dict(capacity=dict(PILOT_CAPACITY, native=dict(PILOT_CAPACITY['native'], GPU_stopped=False))),
    'UID0_hits=1': dict(capacity=dict(PILOT_CAPACITY, native=dict(PILOT_CAPACITY['native'], UID0_hits=1))),
    'UID0_errors=1': dict(capacity=dict(PILOT_CAPACITY, native=dict(PILOT_CAPACITY['native'], UID0_errors=1))),
    'evidence tuple changed': dict(capacity=dict(PILOT_CAPACITY, execution_evidence=dict(PILOT_CAPACITY['execution_evidence'],
                                                                                         recorded_completion_POST_attempts=5))),
    'archive sha256 mismatch': dict(archive_sha256='0' * 64),
    'two raw records': dict(records=(PILOT_RAW, PILOT_RAW)),
    'model id mismatch': dict(records=(dict(PILOT_RAW, model_id='other'),)),
    'pilot mode is full': dict(pilot=dict(PILOT, mode='full')),
    'pilot candidate differs': dict(pilot=dict(PILOT, candidate='other')),
    'pilot immutable config differs': dict(pilot=dict(PILOT, immutable_candidate_configs=dict(cfg='c2'))),
    'pilot predates late binding': dict(pilot={k: v for k, v in PILOT.items() if k != 'predecessor_binding'}),
    'pilot preparer differs': dict(pilot=dict(PILOT, preparer_sha256='f' * 64)),
    'candidate result incomplete': dict(result=dict(PILOT_RESULT, complete=False)),
}


def add_json(t, name, obj):
    payload = json.dumps(obj).encode()
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    t.addfile(info, io.BytesIO(payload))


def pilot_dirs(tmp_path, monkeypatch):
    bakeoff, d = tmp_path/'bakeoff', tmp_path/'dir'
    bakeoff.mkdir()
    d.mkdir()
    monkeypatch.setattr(RUN, 'BAKEOFF', bakeoff)
    return bakeoff, d


def write_pilot(bakeoff, d, capacity=PILOT_CAPACITY, pilot=PILOT, result=PILOT_RESULT,
                records=(PILOT_RAW,), archive_sha256=None):
    """Writes a pilot named p. Each keyword replaces one part, so a case breaks one condition and nothing else."""
    archive = d/'p.archive.tar'
    with tarfile.open(archive, 'w') as t:
        add_json(t, 'permanent/candidate-result.json', result)
        for i, rec in enumerate(records):
            add_json(t, f'permanent/r{i}/raw.json', rec)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (bakeoff/'p.actual-capacity-return.json').write_text(
        json.dumps(dict(capacity, archive=str(archive), archive_sha256=archive_sha256 or digest)))
    (d/'p.prepared.json').write_text(json.dumps(pilot))


def test_pilot_checks_passes_the_clean_pilot(tmp_path, monkeypatch):
    bakeoff, d = pilot_dirs(tmp_path, monkeypatch)
    write_pilot(bakeoff, d)
    cap_sha, archive_sha = RUN.pilot_checks(d, FULL, 'p')
    assert cap_sha == hashlib.sha256((bakeoff/'p.actual-capacity-return.json').read_bytes()).hexdigest()
    assert archive_sha == hashlib.sha256((d/'p.archive.tar').read_bytes()).hexdigest()


@pytest.mark.parametrize('label', list(PILOT_VIOLATIONS))
def test_pilot_checks_refuses_each_violated_condition_alone(tmp_path, monkeypatch, label):
    bakeoff, d = pilot_dirs(tmp_path, monkeypatch)
    write_pilot(bakeoff, d, **PILOT_VIOLATIONS[label])
    with pytest.raises(ValueError):
        RUN.pilot_checks(d, FULL, 'p')


def full_recipe(d):
    """Rewrites the recipe as a full-mode record that carries the frozen keys the pilot must match."""
    (d/'n.prepared.json').write_text(json.dumps(prepared(RECIPE, name='n', unit='workbay-x.scope', gate_token='tok', **FROZEN)))


def test_main_full_mode_refuses_when_the_pilot_fails_one_condition(stubbed_main):
    m = stubbed_main
    full_recipe(m['d'])
    write_pilot(m['bakeoff'], m['d'], capacity=dict(PILOT_CAPACITY, remaining_actor_claim=1))
    calls = []
    m['monkeypatch'].setattr(RUN.subprocess, 'run', lambda *a, **k: calls.append(('run', a)))
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: calls.append(('admit', a)))
    with pytest.raises(SystemExit, match='preflight refused'):
        RUN.main(m['argv'] + ['--pilot', 'p'])
    assert calls == [] and m['runs'] == []


def test_main_full_mode_admits_with_a_clean_pilot_and_binds_its_receipt(stubbed_main):
    m = stubbed_main
    full_recipe(m['d'])
    write_pilot(m['bakeoff'], m['d'])
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: None)
    assert RUN.main(m['argv'] + ['--pilot', 'p']) == 0
    assert m['runs'] == [(CUSTODY_SOURCE, 'QWEN-AB-G2')]
    assert 'QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256' in m['runner'].bootstrap({}, None)


# --- runner v2: preclaim ------------------------------------------------------------------------

def source_report():
    """A healthy source report: every root at BINDING's sha and clean, and the interpreter imports. The TEST-20 baseline."""
    root = dict(head=SHA, clean=True, head_rc=0, diff_rc=0, head_error=None, diff_error=None)
    return dict(repo=dict(root), workspace=dict(root), python=dict(executable=True, import_ok=True, stderr_tail='', error=None))


def report(state='stopped', lease=None, action='auto', expires='2001-01-01T00:00:00Z', publication=True, source=None):
    pub = dict(op='op1', action=action, expires_at=expires, sequence=3) if publication else None
    return dict(gpu=dict(state=state, lease_expires_at=lease), publication=pub,
                source=source_report() if source is None else source)


def test_classify_preclaim_refuses_a_running_gpu():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(state='running'), BINDING)
    assert e.value.cls == 'gpu_not_stopped'


def test_classify_preclaim_refuses_a_set_gpu_lease():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(lease='2026-10-20T13:00:00Z'), BINDING)
    assert e.value.cls == 'gpu_not_stopped'


def test_classify_preclaim_refuses_a_live_start():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(action='start'), BINDING)
    assert e.value.cls == 'live_start'


def test_classify_preclaim_accepts_an_expired_auto():
    r = report(expires='2001-01-01T00:00:00Z')
    assert RUN.classify_preclaim(r, BINDING) == r


def test_classify_preclaim_accepts_stop():
    r = report(action='stop')
    assert RUN.classify_preclaim(r, BINDING) == r


def test_classify_preclaim_refuses_missing_publication():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(publication=False), BINDING)
    assert e.value.cls == 'predecessor_unsettled'


def test_classify_preclaim_refuses_an_unsettled_action():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(action='settle'), BINDING)
    assert e.value.cls == 'predecessor_unsettled'


ZERO = '0' * 40
SOURCE_BREAKS = {
    'repo head mismatch': lambda s: s['repo'].update(head=ZERO),
    'repo dirty': lambda s: s['repo'].update(clean=False),
    'repo head None (rc 128)': lambda s: s['repo'].update(head=None, head_rc=128, clean=False),
    'workspace head mismatch': lambda s: s['workspace'].update(head=ZERO),
    'workspace dirty': lambda s: s['workspace'].update(clean=False),
    'python not executable': lambda s: s['python'].update(executable=False),
    'import failure': lambda s: s['python'].update(import_ok=False, stderr_tail='ModuleNotFoundError: httpx'),
}


def test_classify_preclaim_accepts_the_all_healthy_report_as_the_baseline():
    r = report()
    assert RUN.classify_preclaim(r, BINDING) == r


@pytest.mark.parametrize('label', list(SOURCE_BREAKS))
def test_classify_preclaim_refuses_each_unavailable_source_as_source_unavailable(label):
    src = source_report()
    SOURCE_BREAKS[label](src)
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(source=src), BINDING)
    assert e.value.cls == 'source_unavailable' and e.value.transient is False


def test_classify_preclaim_source_detail_names_the_root_expected_and_observed():
    src = source_report()
    src['workspace']['head'] = ZERO
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(source=src), BINDING)
    assert e.value.detail == (f"workspace {WORKSPACE}: expected HEAD {SHA} clean True rc 0 no error; observed head '{ZERO}' clean True "
                              "head_rc 0 head_error None diff_rc 0 diff_error None; "
                              'rebuild: qwen-latebind/durable-source/build_durable_source.py')


def test_classify_preclaim_keeps_the_gpu_check_ahead_of_the_source_check():
    src = source_report()
    src['repo']['clean'] = False
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(state='running', source=src), BINDING)
    assert e.value.cls == 'gpu_not_stopped'


def test_classify_preclaim_refuses_a_report_without_a_source_mapping_as_malformed():
    r = report()
    del r['source']
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(r, BINDING)
    assert e.value.cls == 'malformed_payload'


# QDSG1-03: every child status is checked, not only head and clean; each row flips one field of the all-healthy report.
ROOT_FIELDS = ('head', 'clean', 'head_rc', 'diff_rc', 'head_error', 'diff_error')
PY_FIELDS = ('executable', 'import_ok', 'error', 'stderr_tail')
ROOT_FLIPS = [(owner, field, value) for owner in ('repo', 'workspace') for field, value in
              [('head_rc', 128), ('diff_rc', 128), ('diff_rc', 1), ('head_error', 'OSError: denied'),
               ('diff_error', 'TimeoutExpired: 15'), ('clean', 1), ('head', None)]]
PYTHON_FLIPS = [('python', 'executable', False), ('python', 'import_ok', None), ('python', 'error', 'OSError: denied')]


@pytest.mark.parametrize('owner,field,value', ROOT_FLIPS + PYTHON_FLIPS)
def test_classify_preclaim_refuses_each_flipped_field_and_names_every_observed_field(owner, field, value):
    src = source_report()
    src[owner][field] = value
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(source=src), BINDING)
    assert e.value.cls == 'source_unavailable' and e.value.transient is False
    assert e.value.detail.startswith(f'{owner} {BINDING[owner]}:')
    observed = PY_FIELDS if owner == 'python' else ROOT_FIELDS
    assert all(f' {key} ' in e.value.detail for key in observed), e.value.detail


SOURCE_SHAPES = {
    'repo missing': lambda s: s.pop('repo'),
    'repo not a mapping': lambda s: s.update(repo='ok'),
    'workspace null': lambda s: s.update(workspace=None),
    'python not a mapping': lambda s: s.update(python=[]),
    'root key missing': lambda s: s['repo'].pop('head_rc'),
    'root error key missing': lambda s: s['workspace'].pop('diff_error'),
    'python key missing': lambda s: s['python'].pop('import_ok'),
    'python stderr_tail missing': lambda s: s['python'].pop('stderr_tail'),
}


@pytest.mark.parametrize('label', list(SOURCE_SHAPES))
def test_classify_preclaim_refuses_a_missing_or_ill_typed_source_mapping_as_malformed(label):
    src = source_report()
    SOURCE_SHAPES[label](src)
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(source=src), BINDING)
    assert e.value.cls == 'malformed_payload'


def test_preclaim_script_has_no_ttl_check_and_compiles():
    src = RUN.preclaim_script('/tmp/qwen-owner-window.abc123', BINDING)
    compile(src, 'preclaim', 'exec')
    assert 'remaining' not in src and '>300' not in src


PRECLAIM_ENV = dict(PATH='/usr/local/bin:/usr/bin:/bin', HOME='/home/gate', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1',
                    OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')


def completed(stdout='', stderr='', returncode=0):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def healthy_child(argv):
    """Each source child succeeds on the bound source: the roots are at SHA and clean, and the interpreter imports."""
    if argv[0] == 'git':
        return completed(stdout=SHA + '\n' if argv[3] == 'rev-parse' else '')
    return completed()


def publish(tmp_path, *ops):
    for op, seq, action in ops:
        (tmp_path/'w'/'ops'/op).mkdir(parents=True, exist_ok=True)
        (tmp_path/'w'/'ops'/op/'publication.json').write_text(json.dumps(dict(action=action, expires_at='2001-01-01T00:00:00Z', sequence=seq)))


class FakeClock:
    """Stands in for time.monotonic. It moves only when a fake child is charged time, so the deadline is observable without sleeping."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


def roots(tmp_path):
    """BINDING with repo and workspace as real directories holding a .git/index, so the preclaim's index copy has bytes to copy."""
    b = dict(BINDING)
    for name in ('repo', 'workspace'):
        (tmp_path/name/'.git').mkdir(parents=True, exist_ok=True)
        (tmp_path/name/'.git'/'index').write_bytes(b'DIRC')
        b[name] = str(tmp_path/name)
    return b


def run_preclaim(monkeypatch, capsys, tmp_path, answer=healthy_child, executable=True, cost=lambda argv: 0.0):
    """Execs the generated preclaim text with subprocess replaced by a recorder, os.access fixed, os.chown a no-op and time.monotonic faked.
    cost(argv) is how long a fake child runs; a child that runs to its timeout raises TimeoutExpired and is charged that timeout.
    Returns the calls and the printed reply."""
    gpu = tmp_path/'gpu.json'
    gpu.write_text(json.dumps(dict(state='stopped', lease_expires_at=None)))
    src = RUN.preclaim_script(str(tmp_path/'w'), roots(tmp_path)).replace("'/run/acx/gpu-state.json'", repr(str(gpu)))
    clock, calls = FakeClock(), []
    recorder = types.ModuleType('subprocess')

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        took = cost(argv)
        clock.now += min(took, kwargs['timeout'])
        if took >= kwargs['timeout']:
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        return answer(argv)

    recorder.run, recorder.TimeoutExpired = run, subprocess.TimeoutExpired
    monkeypatch.setitem(sys.modules, 'subprocess', recorder)
    monkeypatch.setattr(os, 'access', lambda path, mode: executable)
    monkeypatch.setattr(os, 'chown', lambda path, uid, gid: None)
    monkeypatch.setattr(time, 'monotonic', clock.monotonic)
    exec(compile(src, 'preclaim', 'exec'), {'__name__': 'preclaim'})
    return calls, json.loads(capsys.readouterr().out)


def run_local(monkeypatch, capsys, tmp_path, b):
    """Execs the generated preclaim text against the real git as the local uid: the uid 1002 switch is dropped, and os.chown is recorded
    (path, uid, gid, mode at the time of the call) instead of applied. Returns the printed reply, every child's (argv, kwargs) and the chowns."""
    gpu = tmp_path/'gpu.json'
    gpu.write_text(json.dumps(dict(state='stopped', lease_expires_at=None)))
    src = RUN.preclaim_script(str(tmp_path/'w'), b).replace("'/run/acx/gpu-state.json'", repr(str(gpu)))
    real, calls, chowns = subprocess, [], []
    local = types.ModuleType('subprocess')

    def run(argv, **kwargs):
        calls.append((argv, dict(kwargs)))
        for key in ('user', 'group', 'extra_groups'):
            kwargs.pop(key)
        return real.run(argv, **kwargs)

    local.run, local.TimeoutExpired = run, real.TimeoutExpired
    monkeypatch.setitem(sys.modules, 'subprocess', local)
    monkeypatch.setattr(os, 'chown', lambda path, uid, gid: chowns.append((str(path), uid, gid, os.stat(path).st_mode & 0o777)))
    exec(compile(src, 'preclaim', 'exec'), {'__name__': 'preclaim'})
    return json.loads(capsys.readouterr().out), calls, chowns


def git_in(path, *args):
    return subprocess.run(['git', '-C', str(path), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def committed_repo(path):
    """A real repo with one committed file, then stat-only drift on it: the same bytes under an older mtime."""
    path.mkdir(parents=True)
    git_in(path, 'init', '-q')
    (path/'a.txt').write_text('hello\n')
    git_in(path, 'add', 'a.txt')
    git_in(path, 'commit', '-qm', 'init')
    os.utime(path/'a.txt', (946684800, 946684800))
    return path


def test_preclaim_script_reports_the_highest_sequence_publication(monkeypatch, capsys, tmp_path):
    publish(tmp_path, ('a', 1, 'start'), ('b', 2, 'auto'))
    _, rep = run_preclaim(monkeypatch, capsys, tmp_path)
    assert rep['gpu'] == dict(state='stopped', lease_expires_at=None)
    assert rep['publication'] == dict(op='b', action='auto', expires_at='2001-01-01T00:00:00Z', sequence=2)


def test_preclaim_script_composes_the_five_source_children_exactly(monkeypatch, capsys, tmp_path):
    publish(tmp_path, ('op1', 3, 'auto'))
    b = roots(tmp_path)
    calls, rep = run_preclaim(monkeypatch, capsys, tmp_path)
    assert [argv for argv, _ in calls] == [
        ['git', '-C', b['repo'], 'rev-parse', 'HEAD'],
        ['git', '-C', b['repo'], 'diff', '--name-only'],
        ['git', '-C', b['workspace'], 'rev-parse', 'HEAD'],
        ['git', '-C', b['workspace'], 'diff', '--name-only'],
        [b['python'], '-B', '-c', 'import httpx,scripts.eval_harness.bakeoff'],
    ]
    for (argv, kw), timeout in zip(calls, [10, 15, 10, 15, 20]):
        assert kw['timeout'] == timeout, argv
        assert kw['user'] == 1002 and kw['group'] == 1002 and kw['extra_groups'] == [], argv
        assert kw['capture_output'] is True and kw['text'] is True, argv
        assert kw.get('cwd') == (f"{b['workspace']}/apps/prototype-description-service" if argv[0] == b['python'] else None), argv
        env = dict(kw['env'])
        if argv[0] == 'git' and argv[3] == 'diff':
            assert env.pop('GIT_OPTIONAL_LOCKS') == '0' and env.pop('GIT_INDEX_FILE'), argv
        assert env == PRECLAIM_ENV, argv
    assert rep['source'] == source_report()
    assert RUN.classify_preclaim(rep, b) == rep


@pytest.mark.parametrize('target,path,fail', [
    (lambda b: ['git', '-C', b['repo'], 'rev-parse'], ('repo', 'head_error'), lambda argv: OSError('denied')),
    (lambda b: ['git', '-C', b['workspace'], 'diff'], ('workspace', 'diff_error'), lambda argv: subprocess.TimeoutExpired(argv, 15)),
    (lambda b: [b['python']], ('python', 'error'), lambda argv: FileNotFoundError(2, 'No such file or directory')),
], ids=['repo-rev-parse-oserror', 'workspace-diff-timeout', 'python-missing'])
def test_a_source_child_that_cannot_run_is_recorded_and_refused_without_reraising(monkeypatch, capsys, tmp_path, target, path, fail):
    publish(tmp_path, ('op1', 3, 'auto'))
    b = roots(tmp_path)
    prefix = target(b)

    def answer(argv):
        if argv[:len(prefix)] == prefix:
            raise fail(argv)
        return healthy_child(argv)

    _, rep = run_preclaim(monkeypatch, capsys, tmp_path, answer=answer)
    assert rep['source'][path[0]][path[1]] is not None
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(rep, b)
    assert e.value.cls == 'source_unavailable'


# QDSG1-04: the children share one 20 s deadline inside the 30 s ssh, and the JSON is printed whatever each child does.
def test_hung_children_share_one_twenty_second_deadline_and_the_rest_are_skipped(monkeypatch, capsys, tmp_path):
    publish(tmp_path, ('op1', 3, 'auto'))
    b = roots(tmp_path)
    calls, rep = run_preclaim(monkeypatch, capsys, tmp_path, cost=lambda argv: float('inf'))
    assert [kw['timeout'] for _, kw in calls] == [10, 10]
    assert sum(kw['timeout'] for _, kw in calls) <= 20
    src = rep['source']
    assert src['repo']['head_error'].startswith('TimeoutExpired') and src['repo']['diff_error'].startswith('TimeoutExpired')
    assert src['workspace']['head_error'] == 'deadline_exhausted' and src['workspace']['diff_error'] == 'deadline_exhausted'
    assert src['python']['error'] == 'deadline_exhausted'
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(rep, b)
    assert e.value.cls == 'source_unavailable' and e.value.transient is False


def test_a_slow_child_leaves_the_next_child_only_the_rest_of_the_deadline(monkeypatch, capsys, tmp_path):
    publish(tmp_path, ('op1', 3, 'auto'))
    b = roots(tmp_path)

    def cost(argv):
        if argv[:4] == ['git', '-C', b['repo'], 'rev-parse']:
            return 9.5
        return float('inf') if argv[:4] == ['git', '-C', b['repo'], 'diff'] else 0.0

    calls, rep = run_preclaim(monkeypatch, capsys, tmp_path, cost=cost)
    assert [kw['timeout'] for _, kw in calls] == [10, 20 - 9.5]
    assert rep['source']['repo']['head'] == SHA and rep['source']['repo']['diff_error'].startswith('TimeoutExpired')
    assert rep['source']['workspace']['head_error'] == 'deadline_exhausted'
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(rep, b)
    assert e.value.cls == 'source_unavailable'


# QDSG1-05: the read-only preclaim must not rewrite .git/index; the diff child reads a private copy, as uid 1002, and the copy is removed.
def git_index_probe(tmp_path, damage=None):
    repo = committed_repo(tmp_path/'repo')
    if damage == 'missing':
        (repo/'.git'/'index').unlink()
    if damage == 'unreadable':
        (repo/'.git'/'index').chmod(0)
    b = dict(BINDING, source=git_in(repo, 'rev-parse', 'HEAD'), repo=str(repo), workspace=str(repo), python=str(tmp_path/'no-python'))
    return repo, b


def test_plain_git_diff_rewrites_the_index_on_stat_only_drift(tmp_path):
    """The hazard the copy removes, shown on this git: a plain diff rewrites .git/index after stat-only drift, so the next test is not vacuous."""
    repo = committed_repo(tmp_path/'repo')
    index = repo/'.git'/'index'
    before = index.read_bytes()
    assert git_in(repo, 'diff', '--name-only') == ''
    assert index.read_bytes() != before


def test_preclaim_diff_leaves_the_repo_index_bytes_and_mtime_untouched_on_stat_only_drift(monkeypatch, capsys, tmp_path):
    publish(tmp_path, ('op1', 3, 'auto'))
    repo, b = git_index_probe(tmp_path)
    index = repo/'.git'/'index'
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    rep, _, _ = run_local(monkeypatch, capsys, tmp_path, b)
    for name in ('repo', 'workspace'):
        assert rep['source'][name]['diff_rc'] == 0 and rep['source'][name]['diff_error'] is None
        assert rep['source'][name]['clean'] is True
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before


def test_the_diff_child_reads_a_private_index_copy_owned_by_1002_and_removes_it(monkeypatch, capsys, tmp_path):
    repo, b = git_index_probe(tmp_path)
    _, calls, chowns = run_local(monkeypatch, capsys, tmp_path, b)
    diffs = [kw for argv, kw in calls if argv[0] == 'git' and argv[3] == 'diff']
    assert len(diffs) == 2
    for kw in diffs:
        env = kw['env']
        assert env['GIT_OPTIONAL_LOCKS'] == '0' and env['GIT_INDEX_FILE'] != str(repo/'.git'/'index')
        copy = Path(env['GIT_INDEX_FILE'])
        assert not copy.exists() and not copy.parent.exists()
        assert (str(copy.parent), 1002, 1002, 0o700) in chowns
        assert any(c[:3] == (str(copy), 1002, 1002) for c in chowns)


@pytest.mark.parametrize('damage', ['missing', pytest.param('unreadable', marks=pytest.mark.skipif(os.geteuid() == 0, reason='root reads any file'))])
def test_a_missing_or_unreadable_repo_index_is_a_diff_error_and_never_clean(monkeypatch, capsys, tmp_path, damage):
    publish(tmp_path, ('op1', 3, 'auto'))
    _, b = git_index_probe(tmp_path, damage=damage)
    rep, _, _ = run_local(monkeypatch, capsys, tmp_path, b)
    root = rep['source']['repo']
    assert root['diff_error'] is not None and root['clean'] is False and root['diff_rc'] is None
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(rep, b)
    assert e.value.cls == 'source_unavailable'


# --- runner v2: bootstrap -----------------------------------------------------------------------

def test_bootstrap_source_compiles_and_sets_the_gate_token():
    src = RUN.bootstrap_source(RECIPE, 'n', 'gate-tok', 'abc')
    compile(src, 'bootstrap', 'exec')
    assert 'QWEN_AB_SOL_XHIGH_GATE' in src and 'gate-tok' in src
    assert 'QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256' in src and 'abc' in src


def test_bootstrap_source_omits_pilot_env_when_pilot_sha_is_none():
    src = RUN.bootstrap_source(RECIPE, 'n', 'gate-tok', None)
    compile(src, 'bootstrap', 'exec')
    assert 'QWEN_AB_SOL_XHIGH_GATE' in src
    assert 'QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256' not in src


# --- runner seam: the real reviewed runner and the real r6; stand-ins only for the two untracked leaves -------

def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def real_runner(monkeypatch):
    # Only the attributes that r6 and the runner read at import time are stood in; everything else is the real code.
    cap_stub = types.ModuleType('bakeoff_frontier_capacity')
    cap_stub.P, cap_stub.RAWKEY = Path('/nonexistent'), 'raw-key'
    orchestrate_stub = types.ModuleType('orchestrate')
    orchestrate_stub.P = Path('/nonexistent')
    monkeypatch.setitem(sys.modules, 'bakeoff_frontier_capacity', cap_stub)
    monkeypatch.setitem(sys.modules, 'orchestrate', orchestrate_stub)
    r6 = load_path('run_owner_root_fixture_r6', QWEN_AB.parent/'run_owner_root_fixture_r6.py')
    monkeypatch.setitem(sys.modules, 'run_owner_root_fixture_r6', r6)
    return r6, load_path(RUNNER_NAME, RUNNER_REF)


def test_the_real_runner_has_the_seams_that_main_patches(real_runner):
    r6, runner = real_runner
    assert list(inspect.signature(runner.run).parameters) == ['head', 'gate']
    assert len(inspect.signature(runner.inputs).parameters) == 2
    assert len(inspect.signature(runner.bootstrap).parameters) == 2
    assert runner.admission is r6
    inspect.signature(r6.guard).bind()
    assert all(isinstance(getattr(runner, name), str) for name in ('N', 'UNIT', 'ROLE'))


# --- runner preflight: the runner, its leaves and the helper record are checked before anything is run -------

def assert_refused_before_any_probe(m, monkeypatch, pattern):
    probes = []
    monkeypatch.setattr(RUN.subprocess, 'run', lambda *a, **k: probes.append(a))
    with pytest.raises(SystemExit, match=pattern):
        RUN.main(m['argv'])
    assert probes == []


def test_main_refuses_a_checkout_without_the_runner_before_any_probe(operator_checkout, tmp_path, monkeypatch):
    bare = tmp_path/'bare'
    bare.mkdir()
    monkeypatch.setattr(RUN, 'BAKEOFF', bare)
    monkeypatch.setattr(sys, 'path', [str(bare)])
    assert_refused_before_any_probe(operator_checkout, monkeypatch, r'^preflight refused: run_selected_root_resume_qualification is missing')


def test_main_refuses_a_runner_copy_that_differs_by_one_byte(operator_checkout, monkeypatch):
    m = operator_checkout
    (m['bakeoff']/(RUNNER_NAME + '.py')).write_bytes(one_byte_changed(RUNNER_REF.read_bytes()))
    assert_refused_before_any_probe(m, monkeypatch, r'^preflight refused: runner differs from the reviewed reference copy$')


def qwen_ab_with_helper(tmp_path, monkeypatch, helper_bytes):
    """A qwen-ab tree whose reviewed references hold helper_bytes; RUN.HERE points at it."""
    here = tmp_path/'qwen-ab'
    (here/'references'/'admission').mkdir(parents=True)
    (here/'references'/'admission'/(RUNNER_NAME + '.py')).write_bytes(RUNNER_REF.read_bytes())
    (here/'references'/'LEXICON-MIMO-40-LAST40-R1.prepared.json').write_bytes(helper_bytes)
    monkeypatch.setattr(RUN, 'HERE', here)


def test_main_refuses_a_helper_record_with_one_changed_byte(operator_checkout, monkeypatch):
    m = operator_checkout
    (m['d']/'LEXICON-MIMO-40-LAST40-R1.prepared.json').write_bytes(one_byte_changed(HELPER_REF.read_bytes()))
    assert_refused_before_any_probe(m, monkeypatch, r'^preflight refused: helper record sha256')


def test_main_refuses_an_absent_helper_record_with_its_path(operator_checkout, monkeypatch):
    m = operator_checkout
    (m['d']/'LEXICON-MIMO-40-LAST40-R1.prepared.json').unlink()
    assert_refused_before_any_probe(m, monkeypatch, r'^preflight refused: helper record is missing: .*LEXICON-MIMO-40-LAST40-R1\.prepared\.json$')


def test_main_pins_the_helper_sha_even_when_the_reviewed_copy_agrees(operator_checkout, tmp_path, monkeypatch):
    m = operator_checkout
    changed = one_byte_changed(HELPER_REF.read_bytes())
    qwen_ab_with_helper(tmp_path, monkeypatch, changed)
    (m['d']/'LEXICON-MIMO-40-LAST40-R1.prepared.json').write_bytes(changed)
    assert_refused_before_any_probe(m, monkeypatch, r'^preflight refused: helper record sha256')


def test_main_refuses_a_helper_record_that_differs_from_the_reviewed_copy(operator_checkout, tmp_path, monkeypatch):
    m = operator_checkout
    qwen_ab_with_helper(tmp_path, monkeypatch, one_byte_changed(HELPER_REF.read_bytes()))
    assert_refused_before_any_probe(m, monkeypatch, r'^preflight refused: helper record differs from the reviewed reference copy$')


def test_helper_reference_copy_is_the_pinned_record():
    assert hashlib.sha256(HELPER_REF.read_bytes()).hexdigest() == 'f0ca0e59c1bc8db1dd83c99598f82c0fb3665a7dd443f66e44291f44f837a4cd'


def test_main_passes_the_helper_check_with_the_pinned_bytes(stubbed_main):
    m = stubbed_main
    assert hashlib.sha256((m['d']/'LEXICON-MIMO-40-LAST40-R1.prepared.json').read_bytes()).hexdigest() == 'f0ca0e59c1bc8db1dd83c99598f82c0fb3665a7dd443f66e44291f44f837a4cd'
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: None)
    assert RUN.main(m['argv']) == 0
    assert m['runs'] == [(CUSTODY_SOURCE, 'QWEN-AB-G2')]


def test_main_receipt_records_the_sha256_of_each_runner_module_it_resolved(stubbed_main):
    m = stubbed_main
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: None)
    assert RUN.main(m['argv']) == 0
    _, receipt = m['runner'].inputs(CUSTODY_SOURCE, 'QWEN-AB-G2')
    origins = {RUNNER_NAME: m['bakeoff']/(RUNNER_NAME + '.py'), **{name: m['bakeoff']/(name + '.py') for name in LEAVES}}
    assert set(receipt['module_sha256']) == {RUNNER_NAME, *LEAVES}
    # The four stand-ins hold distinct bytes, so a digest taken from the wrong origin cannot match by accident.
    assert len({hashlib.sha256(p.read_bytes()).hexdigest() for p in origins.values()}) == 4
    for name, path in origins.items():
        assert receipt['module_sha256'][name] == hashlib.sha256(path.read_bytes()).hexdigest()


# --- runner v3: main refuses an unbound or unavailable source before any claim -----------------

def rebind(m, raw):
    """Rewrites the recipe and its prepared record together, so the preflight reads raw and its sha256 matches."""
    (m['d']/'n.remote.py').write_bytes(raw)
    (m['d']/'n.prepared.json').write_text(json.dumps(prepared(raw, name='n', mode='pilot', candidate='qwen', unit='workbay-x.scope',
                                                              gate_token='tok', preparer_sha256=hashlib.sha256(SRC).hexdigest())))


def test_main_refuses_a_recipe_still_bound_to_the_sandbox_before_any_ssh(stubbed_main):
    m = stubbed_main
    rebind(m, swapped(REPO_LINE, b"repo=Path('/home/gate/workbay-sandbox')/SOURCE"))
    assert_refused_before_any_probe(m, m['monkeypatch'], r'^preflight refused: recipe binds a reaped WorkBay lane sandbox$')
    assert m['persisted'] == [] and m['runs'] == []


def test_main_refuses_an_unavailable_source_before_the_claim(stubbed_main, capsys):
    m = stubbed_main
    bad = source_report()
    bad['repo']['head'] = '0' * 40
    m['monkeypatch'].setattr(RUN.subprocess, 'run', lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(report(source=bad)), stderr=''))
    admitted = []
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: admitted.append(1))
    assert RUN.main(m['argv']) == 3
    assert admitted == [] and m['runs'] == []
    assert [p.name for p, _ in m['persisted']] == ['n.preclaim.json']
    assert not (m['runner'].P/'n.capacity-claim.json').exists()
    status = json.loads(capsys.readouterr().out)
    assert status['status'] == 'ADMISSION_REFUSED' and status['refusal'].startswith('refusal:source_unavailable:')
    assert status['transient'] is False
