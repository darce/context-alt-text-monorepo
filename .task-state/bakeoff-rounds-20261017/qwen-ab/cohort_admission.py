"""Qwen cohort admission bulkhead: labeled refusals and a co-tenant reserve over the r6 guard (decision 18673)."""
import hashlib
import importlib
import json
import math
import re
import subprocess
import time
from datetime import datetime, timezone

G = 1024**3
CPU_AVG60_MAX = 55
IO_FULL_AVG60_MAX = 15
MEM_HEADROOM_MIN = 3*G
ROOT_USED_PCT_MAX = 90
CPU_CEILING = 3.25
HOST_CPUS = 4
# aura_runtime is SKIP-listed and charged by this fixed reserve; its 4 GiB sits outside the lane ceiling; host memory is enforced live by MEM_HEADROOM_MIN; and prospective_RAM is informational.
AURA_RUNTIME_CPU = 1.5
AURA_RUNTIME_MEMORY = 4*G
LANE_MEMORY_CEILING = 16*G
HOST = 'ubuntu@acx-backend.tail1a44b8.ts.net'
ROOT_PROBE = 'raw_auth_source_gate_root_probe.py'
SKIP = frozenset({'wb', 'Bakeoff', 'aura', 'Canvas', 'aura_runtime'})
AURA_A_PIN = ('a4fabeb0732a36f1610504eacdca8b457346566b', 'gpt-6.1-sol', 'low', 'standard')
EVALUATED = ('ledger_state', 'setup_owner', 'expired_owner_lease', 'owned_unit_over_quota', 'co_tenant_unbounded',
             'co_tenant_reserve', 'root_probe', 'disk_projection', 'cpu_pressure', 'io_pressure', 'memory_headroom',
             'probe_transport', 'malformed_payload')
TRANSIENT = frozenset({'cpu_pressure', 'io_pressure', 'memory_headroom', 'disk_projection', 'co_tenant_reserve',
                       'probe_transport'})
DETERMINISTIC = frozenset({'ledger_state', 'setup_owner', 'expired_owner_lease', 'root_probe', 'owned_unit_over_quota',
                           'co_tenant_unbounded', 'gpu_not_stopped', 'live_start', 'predecessor_unsettled',
                           'malformed_payload'})

ROOT_NAMED_SCRIPT = """import json,math,subprocess
units=UNITS;out={}
def cores(x):
 for suffix,factor in [('us',1e-6),('ms',1e-3),('s',1.)]:
  if x.endswith(suffix):
   try:y=float(x[:-len(suffix)])*factor
   except ValueError:return None
   return y if math.isfinite(y)else None
 return None
def bytes_max(x):
 try:return int(x)
 except ValueError:return None
for n in units:
 out[n]={};total_cpu=0.;total_memory=0;invalid=[]
 commands={'system':['systemctl'],'gate-user':['sudo','-n','-H','-u','gate','env','XDG_RUNTIME_DIR=/run/user/1002','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1002/bus','systemctl','--user']}
 for namespace,prefix in commands.items():
  q=subprocess.check_output(prefix+['show',n,'-p','LoadState','-p','ActiveState','-p','ControlGroup','-p','MainPID','-p','CPUQuotaPerSecUSec','-p','MemoryMax'],text=True,timeout=6)
  v=dict(l.split('=',1)for l in q.splitlines()if '='in l);out[n][namespace]=v
  if v.get('LoadState')=='not-found':
   if v.get('ActiveState')!='inactive'or v.get('ControlGroup')or v.get('MainPID','0')!='0':invalid.append(namespace)
   continue
  cpu=cores(v.get('CPUQuotaPerSecUSec',''));memory=bytes_max(v.get('MemoryMax',''))
  total_cpu=None if cpu is None or total_cpu is None else total_cpu+cpu
  total_memory=None if memory is None or total_memory is None else total_memory+memory
 out[n].update(total_cpu=total_cpu,total_memory=total_memory,invalid_not_found=invalid)
print(json.dumps(out))
"""

NATIVE_SCRIPT = '''import json,pathlib,subprocess,time,os
q=lambda *a:subprocess.check_output(a,text=True,timeout=8)
b=pathlib.Path('/sys/fs/cgroup/user.slice/user-'+str(os.getuid())+'.slice')
units=[]
for line in q('systemctl','--user','list-units','--state=running','--no-legend','--plain','workbay-lane-*.scope','workbay-lane-*.service','workbay-custody-*.scope','workbay-custody-*.service').splitlines():
 n=line.split()[0];r=dict(x.split('=',1)for x in q('systemctl','--user','show',n,'-p','CPUQuotaPerSecUSec','-p','MemoryMax').splitlines()if '='in x);r['unit']=n;units.append(r)
i=dict(l.split(':',1)for l in pathlib.Path('/proc/meminfo').read_text().splitlines());s=dict(l.split()for l in (b/'memory.stat').read_text().splitlines())
mx=(b/'memory.max').read_text().strip();w=None if mx=='max' else int(mx)-max(0,int((b/'memory.current').read_text())-int(s.get('inactive_file',0)))
print(json.dumps({'at':time.time(),'units':units,'cpu':pathlib.Path('/proc/pressure/cpu').read_text(),'io':(b/'io.pressure').read_text(),'physical_mem_available':int(i['MemAvailable'].split()[0])*1024,'working_headroom':w}))
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


def owns(unit, key):
    # The orchestrator names a lane's units key, key-sv, key-rN or key-rN-sv; a bare prefix would also claim a sibling lane.
    return unit == key or re.fullmatch(re.escape(key) + r'(-r[0-9]+)?(-sv)?\.(scope|service)', unit) is not None


def classify_native_units(units, expected):
    owned = {k: [0., 0] for k in expected}
    co_tenant = []
    for row in units:
        unit = row['unit']
        cpu, mem = parse_cpu_quota(row['CPUQuotaPerSecUSec']), parse_memory_max(row['MemoryMax'])
        matches = [k for k in expected if owns(unit, k)]
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


def classify_root_named(out, units):
    # The remote probe only reports; the verdict is made here, so an unbounded or unparseable total is refused by label.
    for n, (cpu, mem) in units.items():
        require('root_probe', n in out, 'no named-unit probe row: ' + n)
        row = out[n]
        require('root_probe', not row['invalid_not_found'], f"named unit not as expected for {n}: {row['invalid_not_found']}")
        require('owned_unit_over_quota', row['total_cpu'] is not None and row['total_cpu'] <= cpu + 1e-8,
                f"{n}: total cpu {row['total_cpu']} over cap {cpu} or unbounded")
        require('owned_unit_over_quota', row['total_memory'] is not None and row['total_memory'] <= mem,
                f"{n}: total memory {row['total_memory']} over cap {mem} or unbounded")


def avg60(text, row):
    # The row is picked by its leading word, and the whole avg60 token must match: a malformed token is never read as its prefix.
    tokens = [t for line in text.splitlines() if line.split()[:1] == [row] for t in line.split() if t.startswith('avg60=')]
    # An unreadable PSI line is treated as over the limit: no value means no admission.
    if len(tokens) != 1 or not re.fullmatch(r'avg60=[0-9]+(\.[0-9]+)?', tokens[0]):
        return float('inf')
    value = float(tokens[0][len('avg60='):])
    return value if math.isfinite(value) and value >= 0 else float('inf')


def require_bounds(k, cpu, mem):
    require('ledger_state', isinstance(cpu, (int, float)) and 0 < cpu <= 4, k)
    require('ledger_state', isinstance(mem, int) and mem > 0, k)


def claim_unit(expected, owners, name, row, cap):
    # Two owner rows naming one unit would overwrite each other's cap, so the second is refused; one row naming it twice is not a duplicate.
    require('ledger_state', owners.setdefault(name, row) == row, 'duplicate unit key across owner rows: ' + name)
    expected[name] = cap


def parse_expires(value):
    # A lease is compared with an aware clock, so a missing, malformed or naive expiry is no lease at all.
    try:
        when = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else None


def owner_rows(ledger):
    rows = {}
    for k, v in ledger.items():
        if k in SKIP or not isinstance(v, dict):
            continue
        require('ledger_state', not v.get('setup_granted'), 'setup granted: ' + k)
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
        require_bounds(k, v.get('aggregate_cpu_cores_max'), v.get('aggregate_memory_bytes_max'))
        require('ledger_state', v.get('physical_key') or v.get('expected_physical_key') or v.get('branch') or v.get('custody_unit') or v.get('native_unit'), k)
        row = dict(v)
        if not row.get('physical_key') and row.get('expected_physical_key'):
            row['physical_key'] = row['expected_physical_key']
        if not row.get('physical_key') and row.get('branch'):
            row['physical_key'] = physical_key(row['branch'])
        rows[k] = row
    for k, v in ledger['WB_operations'].items():
        require('ledger_state', not v.get('setup_granted'), 'setup granted: ' + k)
        if v.get('remaining_actor_claim'):
            cpu, mem = v.get('cpu_cores_aggregate'), v.get('memory_bytes_aggregate')
            key = v.get('physical_key') or v.get('expected_physical_key')
            require_bounds(k, cpu, mem)
            require('ledger_state', key, k)
            rows[k] = dict(v, physical_key=key, aggregate_cpu_cores_max=cpu, aggregate_memory_bytes_max=mem)
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
    # aura and Canvas are SKIP-listed, so owner_rows never charges them; a claim or reservation on either is refused here.
    for name in ('aura', 'Canvas'):
        held = any(ledger[name].get(f) for f in ('remaining_actor_claim', 'reserved_now', 'future_model_claims',
                                                 'aggregate_cpu_cores_max', 'aggregate_memory_bytes_max'))
        require('ledger_state', not held, f'{name} holds a claim or reservation outside owner_rows')
    # aura_runtime and wb are SKIP-listed, so owner_rows never reads them; they are checked here instead.
    rt = ledger.get('aura_runtime', {})
    if rt.get('active'):
        require('ledger_state', isinstance(rt.get('cpu_cores_aggregate'), (int, float)) and rt['cpu_cores_aggregate'] <= AURA_RUNTIME_CPU
                and isinstance(rt.get('memory_bytes_aggregate'), int) and rt['memory_bytes_aggregate'] <= AURA_RUNTIME_MEMORY,
                'aura_runtime exceeds its fixed reserve')
    wb = ledger.get('wb', {})
    require('ledger_state', not (wb.get('remaining_actor_claim') and (wb.get('cpu_cores_aggregate') or wb.get('memory_bytes_aggregate'))),
            'wb row claims resources outside owner_rows')
    rows = owner_rows(ledger)
    aura_a = ledger.get('Aura_WP400_A', {})
    # The .25 is the coordinator's own native budget; 2 GiB is its own memory.
    cpu, memory = .25 + profile['aggregate_cpu_cores_max'], 2*G + profile['aggregate_memory_bytes_max']
    expected, owners = {}, {}
    for k, v in rows.items():
        require('ledger_state', not v.get('setup_granted'), k)
        expires = parse_expires(v.get('expires'))
        require('ledger_state', expires is not None, 'owner lease expires missing, malformed or naive: ' + k)
        require('expired_owner_lease', expires > now, 'Expired owner lease: ' + k)
        cpu += v['aggregate_cpu_cores_max']
        memory += v['aggregate_memory_bytes_max']
        cap_pair = [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
        if v.get('physical_key'):
            claim_unit(expected, owners, 'workbay-lane-' + v['physical_key'], k, cap_pair)
        for field in ('custody_unit', 'custody_scope'):
            if v.get(field):
                claim_unit(expected, owners, v[field], k, cap_pair)
    # The first source offer predates its row; it is never resurrected after return.
    if not aura_a:
        cpu += .5
        memory += 4*G
    units = classify_native_units(native['units'], expected)
    co = units['co_tenant']
    co_cpu = sum(c['cpu'] for c in co)
    co_mem = sum(c['memory'] for c in co)
    # RES-35: the co-tenant reserve counts in every ceiling. A ceiling that fails without the reserve is ledger_state;
    # one that fails only with it is transient, because the co-tenant may finish. Plain ceilings go first, so a
    # deterministic failure is never masked by a transient one (NDM-06).
    ceilings = (
        (cpu <= CPU_CEILING, cpu + co_cpu <= CPU_CEILING, 'CPU ceiling'),
        (cpu + AURA_RUNTIME_CPU <= HOST_CPUS, cpu + co_cpu + AURA_RUNTIME_CPU <= HOST_CPUS, 'host CPU'),
        (memory <= LANE_MEMORY_CEILING, memory + co_mem <= LANE_MEMORY_CEILING, 'memory ceiling'))
    for plain, _, what in ceilings:
        require('ledger_state', plain, what + ' exceeded without co-tenant reserve')
    for _, reserved, what in ceilings:
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
    cpu_avg = avg60(native['cpu'], 'some')
    require('cpu_pressure', cpu_avg < CPU_AVG60_MAX, f'PSI cpu avg60 {cpu_avg}')
    io_full = avg60(native['io'], 'full')
    require('io_pressure', io_full <= IO_FULL_AVG60_MAX, f'PSI io full avg60 {io_full}')
    # working_headroom is None when the cgroup has no memory.max; the physical reading then bounds the headroom alone.
    working = native['working_headroom']
    headroom = native['physical_mem_available'] if working is None else min(native['physical_mem_available'], working)
    require('memory_headroom', headroom >= MEM_HEADROOM_MIN, f'memory headroom {headroom}')
    return dict(at=now.timestamp(), ledger_sha256=hashlib.sha256(json.dumps(ledger, sort_keys=True).encode()).hexdigest(),
                prospective_CPU=cpu + co_cpu + AURA_RUNTIME_CPU, prospective_RAM=memory + co_mem + AURA_RUNTIME_MEMORY,
                projected_root=projected, pending=pending, owned=units['owned'],
                co_tenant_reserve=dict(cpu=co_cpu, memory=co_mem, units=[c['unit'] for c in co]),
                classes_checked=list(EVALUATED))


def probe_argv(host):
    # The argv r6 ssh() builds, so the bulkhead reaches each host the same way the r6 guard did.
    return ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, 'sudo -n python3 -' if host.startswith('ubuntu@') else 'python3 -']


def ssh_json(argv, script, timeout):
    # Transport faults are transient (75). A probe that ran and failed, or replied with something other than a JSON object, is deterministic (3).
    try:
        probe = subprocess.run(argv, input=script, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as e:
        raise AdmissionRefusal('probe_transport', f'{type(e).__name__}: {e}') from e
    if probe.returncode == 255:
        raise AdmissionRefusal('probe_transport', f'ssh exited 255: {(probe.stderr or "").strip()[-300:]}')
    if probe.returncode:
        raise AdmissionRefusal('root_probe', f'probe exited {probe.returncode}: {(probe.stderr or "").strip()[-300:]}')
    try:
        reply = json.loads(probe.stdout)
    except json.JSONDecodeError as e:
        raise AdmissionRefusal('root_probe', f'probe reply is not JSON: {e}') from e
    if not isinstance(reply, dict):
        raise AdmissionRefusal('root_probe', 'probe reply is not a JSON object')
    return reply


def native_units(rows):
    # A dict keyed by native_unit keeps only the later row's cap, so a second row naming the same unit is refused before any probe.
    units = {}
    for name, v in rows.items():
        if v.get('native_unit'):
            require('ledger_state', v['native_unit'] not in units, 'duplicate native unit across owner rows: ' + name)
            units[v['native_unit']] = [v['aggregate_cpu_cores_max'], v['aggregate_memory_bytes_max']]
    return units


def guard():
    # r6 pulls in the orchestration stack, so it is imported only when a live probe runs.
    base = importlib.import_module('run_owner_root_fixture_r6')
    cap = base.cap
    before = cap.LEDGER.read_bytes()
    try:
        ledger = json.loads(before)
        root_units = native_units(owner_rows(ledger))
        root_named_units = ssh_json(probe_argv(HOST), ROOT_NAMED_SCRIPT.replace('UNITS', repr(root_units)), 30) if root_units else {}
        classify_root_named(root_named_units, root_units)
        root = ssh_json(probe_argv(HOST), (base.P/ROOT_PROBE).read_text() + '\n', 30)
        native = ssh_json(probe_argv(base.d.HOST), NATIVE_SCRIPT, 30)
        proof = evaluate(ledger, base.PROFILE, root, native, datetime.now(timezone.utc))
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as e:
        # A malformed payload is a labeled refusal, not an unlabeled exit 1. AdmissionRefusal is an AssertionError, so labeled refusals pass through.
        raise AdmissionRefusal('malformed_payload', f'{type(e).__name__}: {e}') from e
    # The ledger is re-read before the proof is written, so a refused attempt leaves no passing proof behind.
    require('ledger_state', cap.LEDGER.read_bytes() == before, 'Owner event changed ledger; remeasure')
    proof.update(root=root, native=native, root_named_units=root_named_units)
    cap.persist(base.P/(base.N + '.operation-capacity.json'), proof)
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
