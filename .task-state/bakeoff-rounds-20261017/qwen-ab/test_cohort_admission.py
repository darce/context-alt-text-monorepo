"""Tests for cohort_admission and run_qwen_cohort_operation (decision 18673): stdlib only, no ssh, network or GPU."""
import ast
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
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
                 'co_tenant_unbounded', 'gpu_not_stopped', 'live_start', 'predecessor_unsettled'}


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


def test_an_owner_row_without_expires_is_a_labeled_refusal():
    row = owner_row()
    del row['expires']
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(ledger=ledger(OWN=row))
    assert e.value.cls == 'ledger_state'


def test_lane_memory_ceiling_is_named_for_its_lane_scope():
    assert CA.LANE_MEMORY_CEILING == 16*G and not hasattr(CA, 'MEMORY_CEILING')


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
    fake.cap = types.SimpleNamespace(LEDGER=led, persist=lambda path, obj: persisted.append((path, obj)))
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

RECIPE = b"window=Path('/tmp/qwen-owner-window.abc123')\nx = 1\n"
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

def run_fixture(tmp_path):
    d = tmp_path/'dir'
    d.mkdir()
    (d/'n.prepared.json').write_text(json.dumps(prepared(RECIPE, name='n', mode='pilot', candidate='qwen', unit='workbay-x.scope',
                                                          gate_token='tok', preparer_sha256=hashlib.sha256(SRC).hexdigest())))
    (d/'n.remote.py').write_bytes(RECIPE)
    (d/'LEXICON-MIMO-40-LAST40-R1.prepared.json').write_text(json.dumps(dict(stage='S', manifest_sha256='M', source_head='H', gate='GG')))
    payload = json.dumps(dict(status='PASS', source_sha=CUSTODY_SOURCE)).encode()
    with tarfile.open(d/'QWEN-AB-G2.custody.tar', 'w') as t:
        info = tarfile.TarInfo('output/result.json')
        info.size = len(payload)
        t.addfile(info, io.BytesIO(payload))
    bakeoff = tmp_path/'bakeoff'
    bakeoff.mkdir()
    (bakeoff/'QWEN-AB-G2.actual-capacity-return.json').write_text(json.dumps(dict(remaining_actor_claim=0)))
    return d, bakeoff


@pytest.fixture
def stubbed_main(tmp_path, monkeypatch):
    d, bakeoff = run_fixture(tmp_path)
    monkeypatch.setattr(RUN, 'BAKEOFF', bakeoff)
    monkeypatch.setattr(RUN, 'run_git', FakeGit())
    monkeypatch.setattr(RUN.subprocess, 'run', lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(report()), stderr=''))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    persisted, runs = [], []
    fake_runner = types.ModuleType('run_selected_root_resume_qualification')
    fake_runner.admission = types.SimpleNamespace(guard=None, N=None, PROFILE=None)
    fake_runner.cap = types.SimpleNamespace(persist=lambda path, obj: persisted.append((path, obj)))
    fake_runner.run = lambda head, gate: runs.append((head, gate))
    monkeypatch.setitem(sys.modules, 'run_selected_root_resume_qualification', fake_runner)
    argv = ['--name', 'n', '--dir', str(d), '--gate-commit', 'g1']
    return dict(runner=fake_runner, bakeoff=bakeoff, d=d, persisted=persisted, runs=runs, argv=argv, monkeypatch=monkeypatch)


def test_main_admits_then_runs_with_cohort_identity_and_bootstrap(stubbed_main):
    m, admitted = stubbed_main, []
    m['monkeypatch'].setattr(CA, 'admit', lambda *a, **k: admitted.append(1))
    assert RUN.main(m['argv']) is None
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
    assert RUN.main(m['argv'] + ['--pilot', 'p']) is None
    assert m['runs'] == [(CUSTODY_SOURCE, 'QWEN-AB-G2')]
    assert 'QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256' in m['runner'].bootstrap({}, None)


# --- runner v2: preclaim ------------------------------------------------------------------------

def report(state='stopped', lease=None, action='auto', expires='2001-01-01T00:00:00Z', publication=True):
    pub = dict(op='op1', action=action, expires_at=expires, sequence=3) if publication else None
    return dict(gpu=dict(state=state, lease_expires_at=lease), publication=pub)


def test_classify_preclaim_refuses_a_running_gpu():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(state='running'))
    assert e.value.cls == 'gpu_not_stopped'


def test_classify_preclaim_refuses_a_set_gpu_lease():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(lease='2026-10-20T13:00:00Z'))
    assert e.value.cls == 'gpu_not_stopped'


def test_classify_preclaim_refuses_a_live_start():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(action='start'))
    assert e.value.cls == 'live_start'


def test_classify_preclaim_accepts_an_expired_auto():
    r = report(expires='2001-01-01T00:00:00Z')
    assert RUN.classify_preclaim(r) == r


def test_classify_preclaim_accepts_stop():
    r = report(action='stop')
    assert RUN.classify_preclaim(r) == r


def test_classify_preclaim_refuses_missing_publication():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(publication=False))
    assert e.value.cls == 'predecessor_unsettled'


def test_classify_preclaim_refuses_an_unsettled_action():
    with pytest.raises(CA.AdmissionRefusal) as e:
        RUN.classify_preclaim(report(action='settle'))
    assert e.value.cls == 'predecessor_unsettled'


def test_preclaim_script_has_no_ttl_check_and_compiles():
    src = RUN.preclaim_script('/tmp/qwen-owner-window.abc123')
    compile(src, 'preclaim', 'exec')
    assert 'remaining' not in src and '>300' not in src


def test_preclaim_script_reports_the_highest_sequence_publication(tmp_path):
    ops = tmp_path/'w'/'ops'
    for op, seq, act in [('a', 1, 'start'), ('b', 2, 'auto')]:
        (ops/op).mkdir(parents=True)
        (ops/op/'publication.json').write_text(json.dumps(dict(action=act, expires_at='2001-01-01T00:00:00Z', sequence=seq)))
    gpu = tmp_path/'gpu.json'
    gpu.write_text(json.dumps(dict(state='stopped', lease_expires_at=None)))
    src = RUN.preclaim_script(str(tmp_path/'w')).replace("'/run/acx/gpu-state.json'", repr(str(gpu)))
    out = subprocess.run([sys.executable, '-I', '-B', '-'], input=src, text=True, capture_output=True, check=True).stdout
    rep = json.loads(out)
    assert rep['gpu'] == dict(state='stopped', lease_expires_at=None)
    assert rep['publication'] == dict(op='b', action='auto', expires_at='2001-01-01T00:00:00Z', sequence=2)


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
