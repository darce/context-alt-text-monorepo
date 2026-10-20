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
TRANSIENT = {'cpu_pressure', 'io_pressure', 'memory_headroom', 'disk_projection', 'co_tenant_reserve'}
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


# --- classify_native_units ----------------------------------------------------------------------

def test_classify_owned_unit_within_caps_passes():
    out = CA.classify_native_units([dict(unit='workbay-lane-own-x.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))],
                                   {'workbay-lane-own': [.5, 2*G]})
    assert out['owned']['workbay-lane-own'][0] == pytest.approx(.25)
    assert out['owned']['workbay-lane-own'][1] == G
    assert out['co_tenant'] == [] and out['refusals'] == []


def test_classify_owned_unit_over_caps_raises():
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_native_units([dict(unit='workbay-lane-own-x.scope', CPUQuotaPerSecUSec='1s', MemoryMax=str(G))],
                                 {'workbay-lane-own': [.5, 2*G]})
    assert e.value.cls == 'owned_unit_over_quota'


def test_classify_owned_unit_without_bounds_raises():
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.classify_native_units([dict(unit='workbay-lane-own-x.scope', CPUQuotaPerSecUSec='infinity', MemoryMax=str(G))],
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
                    native=native(units=[dict(unit='workbay-lane-own-x.scope', CPUQuotaPerSecUSec='250ms', MemoryMax=str(G))]))
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
                                   native=native(units=[dict(unit='workbay-lane-own-x.scope', CPUQuotaPerSecUSec='1s', MemoryMax=str(G))])),
     'owned_unit_over_quota'),
]


@pytest.mark.parametrize('label,over,cls', REFUSALS, ids=[r[0] for r in REFUSALS])
def test_evaluate_labels_each_refusal_class(label, over, cls):
    with pytest.raises(CA.AdmissionRefusal) as e:
        healthy(**over)
    assert e.value.cls == cls


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

def fake_r6(monkeypatch, tmp_path, led, ssh):
    (tmp_path/'raw_auth_source_gate_root_probe.py').write_text('print(1)\n')
    persisted = []
    fake = types.ModuleType('run_owner_root_fixture_r6')
    fake.cap = types.SimpleNamespace(LEDGER=led, persist=lambda path, obj: persisted.append((path, obj)))
    fake.P, fake.N, fake.PROFILE = tmp_path, 'QWEN-TEST', PROFILE
    fake.d = types.SimpleNamespace(HOST='native-host')
    fake.ssh = ssh
    monkeypatch.setitem(sys.modules, 'run_owner_root_fixture_r6', fake)
    return persisted


def test_guard_probes_then_delegates_to_evaluate(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger()))
    persisted = fake_r6(monkeypatch, tmp_path, led,
                        lambda host, script, timeout=30: native() if host == 'native-host' else root())
    before, got, proof = CA.guard()
    assert before == led.read_bytes() and got == ledger()
    assert persisted == [(tmp_path/'QWEN-TEST.operation-capacity.json', proof)]
    assert proof['root']['euid'] == 0 and proof['native']['units'] == []


def test_guard_refuses_when_ledger_changes_during_probe(tmp_path, monkeypatch):
    led = tmp_path/'ledger.json'
    led.write_text(json.dumps(ledger()))

    def ssh(host, script, timeout=30):
        if host == 'native-host':
            led.write_text(json.dumps(ledger(note='moved')))
            return native()
        return root()
    fake_r6(monkeypatch, tmp_path, led, ssh)
    with pytest.raises(CA.AdmissionRefusal) as e:
        CA.guard()
    assert e.value.cls == 'ledger_state'


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
    (d/'n.prepared.json').write_text(json.dumps(prepared(RECIPE, mode='pilot', candidate='qwen', unit='workbay-x.scope',
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
    return dict(runner=fake_runner, bakeoff=bakeoff, persisted=persisted, runs=runs, argv=argv, monkeypatch=monkeypatch)


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


@pytest.mark.parametrize('cls,code', [('cpu_pressure', 75), ('setup_owner', 3)])
def test_main_maps_admission_refusal_to_exit_code_without_running(stubbed_main, cls, code, capsys):
    def refuse(*a, **k):
        raise CA.AdmissionRefusal(cls, 'x')
    stubbed_main['monkeypatch'].setattr(CA, 'admit', refuse)
    assert RUN.main(stubbed_main['argv']) == code
    assert stubbed_main['runs'] == []
    status = json.loads(capsys.readouterr().out)
    assert status == dict(status='ADMISSION_REFUSED', refusal=f'refusal:{cls}: x', transient=code == 75)


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
