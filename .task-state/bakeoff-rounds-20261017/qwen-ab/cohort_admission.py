"""Qwen cohort admission bulkhead: labeled refusals and a co-tenant reserve over the r6 guard (decision 18673)."""
import hashlib
import importlib
import json
import math
import re
import time
from datetime import datetime, timezone

G = 1024**3
CPU_AVG60_MAX = 55
IO_FULL_AVG60_MAX = 15
MEM_HEADROOM_MIN = 3*G
ROOT_USED_PCT_MAX = 90
CPU_CEILING = 3.25
GUEST_CPU = 1.5
HOST_CPUS = 4
MEMORY_CEILING = 16*G
GUEST_MEMORY = 4*G
HOST = 'ubuntu@acx-backend.tail1a44b8.ts.net'
ROOT_PROBE = 'raw_auth_source_gate_root_probe.py'
SKIP = frozenset({'wb', 'Bakeoff', 'aura', 'Canvas', 'aura_runtime'})
AURA_A_PIN = ('a4fabeb0732a36f1610504eacdca8b457346566b', 'gpt-6.1-sol', 'low', 'standard')
EVALUATED = ('ledger_state', 'setup_owner', 'expired_owner_lease', 'owned_unit_over_quota', 'co_tenant_unbounded',
             'co_tenant_reserve', 'root_probe', 'disk_projection', 'cpu_pressure', 'io_pressure', 'memory_headroom')
TRANSIENT = frozenset({'cpu_pressure', 'io_pressure', 'memory_headroom', 'disk_projection', 'co_tenant_reserve'})
DETERMINISTIC = frozenset({'ledger_state', 'setup_owner', 'expired_owner_lease', 'root_probe', 'owned_unit_over_quota',
                           'co_tenant_unbounded', 'gpu_not_stopped', 'live_start', 'predecessor_unsettled'})

ROOT_NAMED_SCRIPT = """import json,subprocess
units=UNITS;out={}
for n,(c,m)in units.items():
 out[n]={};total_cpu=0.;total_memory=0
 commands={'system':['systemctl'],'gate-user':['sudo','-n','-H','-u','gate','env','XDG_RUNTIME_DIR=/run/user/1002','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1002/bus','systemctl','--user']}
 for namespace,prefix in commands.items():
  q=subprocess.check_output(prefix+['show',n,'-p','LoadState','-p','ActiveState','-p','ControlGroup','-p','MainPID','-p','CPUQuotaPerSecUSec','-p','MemoryMax'],text=True,timeout=6)
  v=dict(l.split('=',1)for l in q.splitlines()if '='in l);out[n][namespace]=v
  if v['LoadState']=='not-found':
   assert v['ActiveState']=='inactive'and not v['ControlGroup'],(n,namespace,v)
   if 'MainPID'in v:assert v['MainPID']=='0',(n,namespace,v)
   continue
  cpu=v['CPUQuotaPerSecUSec']
  for suffix,factor in [('us',1e-6),('ms',1e-3),('s',1.)]:
   if cpu.endswith(suffix):actual=float(cpu[:-len(suffix)])*factor;break
  else:raise AssertionError('Unbounded existing native CPU')
  total_cpu+=actual;total_memory+=int(v['MemoryMax'])
 assert total_cpu<=c+1e-8 and total_memory<=m,(n,out[n])
print(json.dumps(out))
"""

NATIVE_SCRIPT = '''import json,pathlib,subprocess,time,os
q=lambda *a:subprocess.check_output(a,text=True,timeout=8)
b=pathlib.Path('/sys/fs/cgroup/user.slice/user-'+str(os.getuid())+'.slice')
units=[]
for line in q('systemctl','--user','list-units','--state=running','--no-legend','--plain','workbay-lane-*.scope','workbay-lane-*.service','workbay-custody-*.scope','workbay-custody-*.service').splitlines():
 n=line.split()[0];r=dict(x.split('=',1)for x in q('systemctl','--user','show',n,'-p','CPUQuotaPerSecUSec','-p','MemoryMax').splitlines()if '='in x);r['unit']=n;units.append(r)
i=dict(l.split(':',1)for l in pathlib.Path('/proc/meminfo').read_text().splitlines());s=dict(l.split()for l in (b/'memory.stat').read_text().splitlines())
print(json.dumps({'at':time.time(),'units':units,'cpu':pathlib.Path('/proc/pressure/cpu').read_text(),'io':(b/'io.pressure').read_text(),'physical_mem_available':int(i['MemAvailable'].split()[0])*1024,'working_headroom':int((b/'memory.max').read_text())-max(0,int((b/'memory.current').read_text())-int(s.get('inactive_file',0)))}))
'''


class AdmissionRefusal(AssertionError):
    def __init__(self, cls, detail):
        if cls not in TRANSIENT | DETERMINISTIC:
            raise ValueError(f'unknown admission refusal class: {cls}')
        super().__init__(f'refusal:{cls}: {detail}')
        self.cls, self.detail, self.transient = cls, detail, cls in TRANSIENT


def require(cls, ok, detail):
    if not ok:
        raise AdmissionRefusal(cls, detail)


def parse_cpu_quota(value):
    # 'us' and 'ms' are tested before 's' because 'ms' also ends in 's'.
    for suffix, divisor in (('us', 1e6), ('ms', 1e3), ('s', 1.)):
        if value.endswith(suffix):
            try:
                cpu = float(value[:-len(suffix)]) / divisor
            except ValueError:
                return None
            return cpu if math.isfinite(cpu) else None
    return None


def parse_memory_max(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def physical_key(branch):
    return re.sub('[^A-Za-z0-9._-]', '-', branch)[:40] + '-' + hashlib.sha256(branch.encode()).hexdigest()[:8]


def classify_native_units(units, expected):
    owned = {k: [0., 0] for k in expected}
    co_tenant = []
    for row in units:
        unit = row['unit']
        cpu, mem = parse_cpu_quota(row['CPUQuotaPerSecUSec']), parse_memory_max(row['MemoryMax'])
        matches = [k for k in expected if unit.startswith(k)]
        if matches:
            require('owned_unit_over_quota', cpu is not None and mem is not None, 'unbounded owned native unit: ' + unit)
            k = max(matches, key=len)
            owned[k][0] += cpu
            owned[k][1] += mem
        else:
            # RES-35: a co-tenant lane is reserved against, not refused for being unreconciled.
            require('co_tenant_unbounded', cpu is not None and mem is not None, 'unbounded co-tenant native unit: ' + unit)
            co_tenant.append(dict(unit=unit, cpu=cpu, memory=mem))
    for k, (cpu, mem) in owned.items():
        require('owned_unit_over_quota', cpu <= expected[k][0] + 1e-8 and mem <= expected[k][1],
                f'{k}: cpu {cpu} memory {mem} over caps {expected[k]}')
    return dict(owned=owned, co_tenant=co_tenant, refusals=[])


def avg60(text, pattern):
    m = re.search(pattern, text)
    # An unreadable PSI line is treated as over the limit: no value means no admission.
    return float(m.group(1)) if m else float('inf')


def owner_rows(ledger):
    rows = {}
    for k, v in ledger.items():
        if k in SKIP or not isinstance(v, dict):
            continue
        if not (v.get('remaining_actor_claim') or v.get('reserved_now') or v.get('future_model_claims')):
            continue
        if v.get('aggregate_cpu_cores_max') == 0 and v.get('aggregate_memory_bytes_max') == 0:
            phase = v.get('VM_phase_retirement', {})
            require('ledger_state', not v.get('remaining_actor_claim') and not v.get('future_model_claims') and not v.get('setup_granted'), k)
            require('ledger_state', phase.get('authority_decision') == 18330 and phase.get('phase') == 'host_custody_verification_no_VM_execution', k)
            require('ledger_state', phase.get('transport_fsync_complete') and phase.get('remote_all_lstat_unchanged') and phase.get('native_wrapper_model_archive_inactive'), k)
            require('ledger_state', phase.get('UID0_hits') == 0 and phase.get('UID0_errors') == 0 and phase.get('PG4healthy'), k)
            require('ledger_state', phase.get('remaining_VM_actor_claim') == 0 and phase.get('remaining_retention_claim') == 1, k)
            # Disk remains charged in pending_reservations; this phase has no VM execution.
            continue
        cpu, mem = v.get('aggregate_cpu_cores_max'), v.get('aggregate_memory_bytes_max')
        require('ledger_state', isinstance(cpu, (int, float)) and 0 < cpu <= 4, k)
        require('ledger_state', isinstance(mem, int) and mem > 0, k)
        require('ledger_state', v.get('physical_key') or v.get('expected_physical_key') or v.get('branch') or v.get('custody_unit') or v.get('native_unit'), k)
        row = dict(v)
        if not row.get('physical_key') and row.get('expected_physical_key'):
            row['physical_key'] = row['expected_physical_key']
        if not row.get('physical_key') and row.get('branch'):
            row['physical_key'] = physical_key(row['branch'])
        rows[k] = row
    for k, v in ledger['WB_operations'].items():
        if v.get('remaining_actor_claim'):
            rows[k] = dict(v, physical_key=v.get('physical_key') or v.get('expected_physical_key'),
                           aggregate_cpu_cores_max=v['cpu_cores_aggregate'], aggregate_memory_bytes_max=v['memory_bytes_aggregate'])
    aura_a = ledger.get('Aura_WP400_A', {})
    if aura_a.get('remaining_actor_claim'):
        require('ledger_state', (aura_a['source_commit'], aura_a['model'], aura_a['effort'], aura_a['speed']) == AURA_A_PIN, 'Aura_WP400_A pin changed')
        require('ledger_state', (aura_a['aggregate_cpu_cores_max'], aura_a['aggregate_memory_bytes_max'], aura_a['forward_disk_bytes'], aura_a['scratch_max_bytes']) == (.5, 3*G, 4*G, G//2), 'Aura_WP400_A resources changed')
        rows['Aura_WP400_A'] = dict(aura_a, physical_key=physical_key(aura_a['branch']))
    return rows


def evaluate(ledger, profile, root, native, now):
    require('ledger_state', ledger['pending_reservations_complete'], 'pending reservations incomplete')
    bakeoff = ledger['Bakeoff']
    require('ledger_state', not bakeoff['remaining_actor_claim'] and not bakeoff['reserved_now'], 'Bakeoff claim or reservation still open')
    owner = ledger['setup_owner']
    require('setup_owner', owner is None or (isinstance(owner, str) and owner.startswith('Owner-coordinated-next')), 'Actual shared setup owner must return first')
    require('ledger_state', not ledger['aura']['active_models'] and not ledger['aura']['setup_granted'], 'Reconcile new Aura profile before this claim')
    require('ledger_state', not ledger['Canvas']['active_models'] and not ledger['Canvas']['setup_granted'], 'Canvas active or setup granted')
    rows = owner_rows(ledger)
    aura_a = ledger.get('Aura_WP400_A', {})
    # The .25 is the coordinator's own native budget; 2 GiB is its own memory.
    cpu, memory = .25 + profile['aggregate_cpu_cores_max'], 2*G + profile['aggregate_memory_bytes_max']
    expected = {}
    for k, v in rows.items():
        require('ledger_state', not v.get('setup_granted'), k)
        require('expired_owner_lease', datetime.fromisoformat(v['expires']) > now, 'Expired owner lease: ' + k)
        cpu += v['aggregate_cpu_cores_max']
        memory += v['aggregate_memory_bytes_max']
        if v.get('physical_key'):
            expected['workbay-lane-' + v['physical_key']] = [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
        for field in ('custody_unit', 'custody_scope'):
            if v.get(field):
                expected[v[field]] = [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
    # The first source offer predates its row; it is never resurrected after return.
    if not aura_a:
        cpu += .5
        memory += 4*G
    units = classify_native_units(native['units'], expected)
    co = units['co_tenant']
    co_cpu = sum(c['cpu'] for c in co)
    co_mem = sum(c['memory'] for c in co)
    # RES-35: the co-tenant reserve counts in every ceiling. A ceiling that fails without the reserve is ledger_state;
    # one that fails only with it is transient, because the co-tenant may finish.
    for plain, reserved, what in (
            (cpu <= CPU_CEILING, cpu + co_cpu <= CPU_CEILING, 'CPU ceiling'),
            (cpu + GUEST_CPU <= HOST_CPUS, cpu + co_cpu + GUEST_CPU <= HOST_CPUS, 'host CPU'),
            (memory <= MEMORY_CEILING, memory + co_mem <= MEMORY_CEILING, 'memory ceiling')):
        require('ledger_state', plain, what + ' exceeded without co-tenant reserve')
        require('co_tenant_reserve', reserved, what + ' exceeded only with co-tenant reserve')
    require('ledger_state', ledger['runtime_reserve_bytes'] == 3*G and ledger['emergency_reserve_bytes'] == 1400000000, 'reserve sizes changed')
    require('root_probe', root['euid'] == 0 and not root['hits'] and not root['unknown'] and root['pg_all_healthy'], 'root probe not clean')
    pending = sum(v['reserved_bytes'] for v in ledger['pending_reservations']) + ledger['runtime_reserve_bytes'] + ledger['emergency_reserve_bytes'] + G
    if not aura_a:
        pending += 4*G + G//2
    a = root['df'].splitlines()[1].split()
    used, free = int(a[2])*1024, int(a[3])*1024
    projected = math.ceil((used+pending)/(used+free)*100)
    require('disk_projection', int(a[4].strip('%')) < ROOT_USED_PCT_MAX and projected < ROOT_USED_PCT_MAX, f'root used {a[4]}, projected {projected}%')
    cpu_avg = avg60(native['cpu'], r'avg60=([0-9.]+)')
    require('cpu_pressure', cpu_avg < CPU_AVG60_MAX, f'PSI cpu avg60 {cpu_avg}')
    io_full = avg60(native['io'], r'full avg10=[^ ]+ avg60=([0-9.]+)')
    require('io_pressure', io_full <= IO_FULL_AVG60_MAX, f'PSI io full avg60 {io_full}')
    headroom = min(native['physical_mem_available'], native['working_headroom'])
    require('memory_headroom', headroom >= MEM_HEADROOM_MIN, f'memory headroom {headroom}')
    return dict(at=now.timestamp(), ledger_sha256=hashlib.sha256(json.dumps(ledger, sort_keys=True).encode()).hexdigest(),
                prospective_CPU=cpu + co_cpu + GUEST_CPU, prospective_RAM=memory + co_mem + GUEST_MEMORY,
                projected_root=projected, pending=pending, owned=units['owned'],
                co_tenant_reserve=dict(cpu=co_cpu, memory=co_mem, units=[c['unit'] for c in co]),
                classes_checked=list(EVALUATED))


def guard():
    # r6 pulls in the orchestration stack, so it is imported only when a live probe runs.
    base = importlib.import_module('run_owner_root_fixture_r6')
    cap = base.cap
    before = cap.LEDGER.read_bytes()
    ledger = json.loads(before)
    root_units = {v['native_unit']: [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
                  for v in owner_rows(ledger).values() if v.get('native_unit')}
    root_named_units = base.ssh(HOST, ROOT_NAMED_SCRIPT.replace('UNITS', repr(root_units))) if root_units else {}
    root = base.ssh(HOST, (base.P/ROOT_PROBE).read_text() + '\n')
    native = base.ssh(base.d.HOST, NATIVE_SCRIPT)
    proof = evaluate(ledger, base.PROFILE, root, native, datetime.now(timezone.utc))
    proof.update(root=root, native=native, root_named_units=root_named_units)
    cap.persist(base.P/(base.N + '.operation-capacity.json'), proof)
    require('ledger_state', cap.LEDGER.read_bytes() == before, 'Owner event changed ledger; remeasure')
    return before, ledger, proof


def admit(attempt=guard, attempts=6, interval=60, sleep=time.sleep):
    # RES-24: transient pressure gets a bounded number of attempts; a deterministic refusal stops after one (NDM-06).
    for n in range(1, attempts + 1):
        try:
            return attempt()
        except AdmissionRefusal as e:
            if not e.transient:
                raise
            last = e
        if n < attempts:
            sleep(interval)
    raise AdmissionRefusal(last.cls, f'{last.detail}; exhausted after {attempts} attempts')
