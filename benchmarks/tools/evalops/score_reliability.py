"""Bounded, pure offline repeated-task scoring (no runner integration).

API: score(candidates, trials=None, *, design=None, artifacts=None). All inputs
are JSON values, are bounded and never mutated. CLI: python -m
benchmarks.tools.evalops.score_reliability --input request.json [--output report.json].
The request has candidates, and optional trials/design/artifacts. No paths in
artifact references are opened, and no commands, providers or databases run.

Input contract (v1 projection, not a new dataset admission authority):
* candidates use dataset-v1 field names. Current 1.0.0 quarantined records
  cannot establish task reliability. Future admitted projections require replay
  input/source_context/rubric, independent_label (artifact ref), substantiated
  grouping, exposure evidence, source refs, hashes, and execution_pins. Candidate
  content_sha256 is the dataset canonical row hash excluding that field.
* artifacts maps ref -> exact UTF-8 text. Refs are {ref, sha256, version}; version
  is optional here, matching trajectory artifacts. Digests verify supplied bytes
  only, never authenticity, source-time, human independence or live acceptance.
* design: version=evalops.reliability-design.v1, cohort_id, case_ids, ks, arms,
  treatment_fields, schedule, practical_delta, bootstrap, manifest. arms maps
  names to {protocol, pins}; pins has every PIN_FIELDS key. protocol binds the
  canonical JSON of pins. Only declared treatment fields may differ across arms;
  rubric is held fixed. schedule maps every case to ordered slots
  {repeat_id, seed, order:[arm names]}. Seed/order vary only by these slots.
  manifest binds canonical JSON of design excluding manifest. Its source-time
  and predeclaration are UNKNOWN; caller must freeze externally before execution.
  pins.source binds {sources:[candidate source objects]} for this cohort.
  Candidate source.snapshot and snapshot_sha256 bind a supplied JSON array of
  original rows; source_id resolves its id and row_sha256 covers canonical row
  JSON. Protocol/input-lock digests must also resolve to supplied artifact bytes.
* trials: trial_id, case_id, arm, repeat_id, seed, order (zero-based position),
  cohort_id, case_sha256, dataset_version, group_id, root_cause_id, protocol,
  pins, input, source_context, execution, oracle, usage, cost. execution binds
  {trial: all trial fields except execution/oracle/usage/cost, status}, where
  status is executed, dispatch_refused, not_executed or unknown. Executed
  failures remain attempts; process success is never a task oracle.
* oracle binds {trial_id, execution_sha256, case_sha256, rubric_sha256,
  independent_label_sha256, outcome:pass|fail|unknown|not_evaluated,
  checker, checks}. checker is {kind:independent_human|deterministic, evidence}
  with evidence an artifact of the independent check. LLM judges are unavailable
  in this slice: EVAL-12 human validation and EVAL-13 protocol evidence require
  separate admission, not a self-asserted validation boolean. checks contains
  {kind:final_goal|forbidden_effect, status:pass|fail|unknown|not_evaluated,
  evidence}. At least one of each kind is required. All must pass for pass;
  an observed failure supports fail; unknown never becomes fail or zero.

One fixed eligible intersection across all arms and ks is used. Every planned
attempt must have matching pins and a checked outcome. Any unavailable attempt
withholds its entire case; exclusions/counts and every supplied attempt remain
visible. Estimates are case-macro descriptive values on that intersection, not
population rates or causal claims. No weighted Wilson or population inference.
An unavailable case withholds its entire declared linked task/root/group
component; exclusions cannot break the original transitive linkage closure.
pass@k = 1 - C(n-c,k)/C(n,k); pass^k = C(c,k)/C(n,k), within each case.

Bootstrap design: sha256-cluster-stratified/v1, seed integer, resamples 100..2000.
Union shared group_id, root_cause_id and canonical_task_id transitively before
sampling; preserve every case, arm and repeat in each cluster. Cross-stratum
clusters withhold uncertainty. Resample clusters within each stratum, retaining
original stratum case shares and case-macro ratios within strata. Report
percentile 95% intervals only with >=3 clusters in every stratum and >=4 total,
nondegenerate draws and nonzero interval width. This is a conservative support
policy, not a coverage guarantee. Tiny/degenerate samples never get [x,x].
Paired deltas are right minus left, on the same cases and the same draws.

Canon v0.26.2: [EVAL-13] Pin the judging protocol (AI Engineering), [EVAL-12]
Validate the judge against humans (AI Engineering), [HITL-05] Agreement is a
diagnostic, not the truth (Human-in-the-Loop ML), [CAL-02] Unknown is a valid
result (Designing Machine Learning Systems), [PROV-01] Every output walks back
to its evidence (Model Cards + AI Engineering). Principles 13/15 and the
evidence-before-commitment/measurement-integrity cards motivate evidence holds,
fixed denominators and explicit missingness. Faithfulness is not measured here;
context-obedience-is-a-separate-capability requires its own human-validated
context-arm design. Historical review consistency and dispatch infrastructure
are separate from runtime goal outcomes. Export success is not acceptance.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path


MAX_BYTES = 16 * 1024 * 1024
MAX_CASES, MAX_TRIALS, MAX_K = 1000, 20000, 1000
MAX_NODES, MAX_DEPTH, MAX_BOOT_WORK = 300000, 40, 2000000
PIN_FIELDS = (
    'prompt', 'model', 'rubric', 'decoding', 'environment', 'config',
    'runtime', 'command', 'source', 'order_handling', 'task_version',
)
BOOT_VERSION = 'sha256-cluster-stratified/v1'
TRIAL_FIELDS = set('''trial_id case_id arm repeat_id seed order cohort_id case_sha256
    dataset_version group_id root_cause_id protocol pins input source_context
    execution oracle usage cost'''.split())


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _bounded(value):
    """Bound public API input too; iterative traversal precedes JSON recursion."""
    stack, count = [(value, 0)], 0
    while stack:
        item, depth = stack.pop()
        count += 1
        _require(count <= MAX_NODES and depth <= MAX_DEPTH, 'JSON structure limit exceeded')
        if isinstance(item, dict):
            _require(all(isinstance(k, str) for k in item), 'JSON keys must be strings')
            stack.extend((v, depth + 1) for v in item.values())
        elif isinstance(item, list):
            stack.extend((v, depth + 1) for v in item)
        elif type(item) in (int, float):
            _require(abs(item) <= 2**53 and math.isfinite(item), 'number out of bounded finite range')
        else:
            _require(item is None or type(item) in (str, bool), 'expected JSON value')
    _require(len(_canonical(value).encode('utf-8')) <= MAX_BYTES, 'JSON byte limit exceeded')


def _object(value, required, allowed, name):
    _require(isinstance(value, dict), f'{name} must be an object')
    _require(required <= value.keys() <= allowed, f'{name} fields invalid')


def _parse(text):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f'duplicate JSON key {key!r}')
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f'invalid JSON constant {value}')

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except RecursionError as exc:
        raise ValueError('JSON nesting limit exceeded') from exc
    _bounded(value)
    return value


def pass_metrics(n, c, k):
    """Exact finite-trial combinatorial estimators; invalid counts raise ValueError."""
    _require(all(type(v) is int for v in (n, c, k)), 'n/c/k must be integers')
    _require(0 <= c <= n <= MAX_TRIALS and 1 <= k <= min(n, MAX_K), 'require 0<=c<=n and 1<=k<=n within bounds')
    denominator = math.comb(n, k)
    return {'pass_at_k': 1 - math.comb(n - c, k) / denominator,
            'pass_pow_k': math.comb(c, k) / denominator}


class _Evidence:
    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.checked = {}
        self.parsed = {}
        self.digests = {hashlib.sha256(v.encode('utf-8')).hexdigest() for v in artifacts.values()}

    def text(self, pin):
        if not isinstance(pin, dict) or not _text(pin.get('ref')) or not _hash(pin.get('sha256')):
            return None
        key = (pin['ref'], pin['sha256'])
        if key in self.checked:
            return self.checked[key]
        value = self.artifacts.get(pin['ref'])
        if not isinstance(value, str):
            return None
        result = value if hashlib.sha256(value.encode('utf-8')).hexdigest() == pin['sha256'] else None
        self.checked[key] = result
        return result

    def json(self, pin):
        text = self.text(pin)
        if text is None:
            return None
        key = (pin['ref'], pin['sha256'])
        if key in self.parsed:
            return self.parsed[key]
        try:
            value = _parse(text)
        except ValueError:
            value = None
        self.parsed[key] = value
        return value


def _candidate_reasons(row, evidence):
    reasons = []
    if row.get('dataset_version') == '1.0.0':
        reasons.append('candidate_release_cannot_admit')
    if row.get('status') != 'admitted' or row.get('quarantine_reasons') != []:
        reasons.append('candidate_quarantined_or_not_admitted')
    if row.get('independent_gold_status') != 'available' or evidence.text(row.get('independent_label')) is None:
        reasons.append('needs_labels')
    for field in ('input', 'source_context', 'expected_output_or_rubric'):
        if evidence.text(row.get(field)) is None:
            reasons.append(f'{field}_unavailable')
    for field in ('protocol_sha256', 'input_lock_sha256', 'content_sha256'):
        if not _hash(row.get(field)):
            reasons.append(f'{field}_unavailable')
    for field in ('protocol_sha256', 'input_lock_sha256'):
        if not isinstance(row.get(field), str) or row[field] not in evidence.digests:
            reasons.append(f'{field}_bytes_unavailable')
    content = {k: v for k, v in row.items() if k != 'content_sha256'}
    if row.get('content_sha256') != hashlib.sha256(_canonical(content).encode('utf-8')).hexdigest():
        reasons.append('candidate_content_hash_mismatch')
    group = row.get('grouping') or {}
    if not isinstance(group, dict) or group.get('linkage_status') != 'substantiated' or not all(
        _text(group.get(k)) for k in ('canonical_task_id', 'group_id', 'root_cause_id')
    ) or not isinstance(group.get('evidence'), list) or not group['evidence'] or not all(evidence.text(p) is not None for p in group['evidence']):
        reasons.append('grouping_unavailable')
    exposure = row.get('exposure') or {}
    if not isinstance(exposure, dict) or exposure.get('system_under_test') != 'unexposed' or evidence.text(exposure.get('attestation')) is None:
        reasons.append('exposure_unavailable')
    pins = row.get('execution_pins') or {}
    if not isinstance(pins, dict) or any(evidence.text(pins.get(k)) is None for k in (
        'prompt', 'decoding', 'environment', 'config'
    )) or not isinstance(pins.get('model'), dict) or not all(_text(pins['model'].get(k)) for k in (
        'provider', 'model_id', 'revision'
    )) or type(pins.get('seed')) is not int or not all(_text(pins.get(k)) for k in ('order_handling', 'task_version')):
        reasons.append('candidate_execution_pins_unavailable')
    if not all(_text(row.get(k)) and row[k] != 'unknown' for k in ('track', 'stratum')):
        reasons.append('track_or_stratum_unknown')
    # Dataset source objects have a different shape from trajectory artifact refs.
    source = row.get('source')
    if not isinstance(source, dict) or not all(_text(source.get(k)) for k in ('system', 'table', 'snapshot')) or not (
        type(source.get('source_id')) is int or _text(source.get('source_id'))
    ) or not all(_hash(source.get(k)) for k in ('snapshot_sha256', 'row_sha256')):
        reasons.append('source_unavailable')
    else:
        snapshot = evidence.json({'ref': source['snapshot'], 'sha256': source['snapshot_sha256']})
        originals = [s for s in snapshot if isinstance(s, dict) and s.get('id') == source['source_id']] if isinstance(snapshot, list) else []
        if len(originals) != 1 or hashlib.sha256(_canonical(originals[0]).encode('utf-8')).hexdigest() != source['row_sha256']:
            reasons.append('source_row_unavailable_or_mismatch')
    return reasons


def _design(design, ids, evidence):
    fields = set('version cohort_id case_ids ks arms treatment_fields schedule practical_delta bootstrap manifest'.split())
    _object(design, fields, fields, 'design')
    _require(design['version'] == 'evalops.reliability-design.v1', 'unsupported design version')
    _require(_text(design['cohort_id']), 'cohort_id required')
    cohort = design['case_ids']
    _require(isinstance(cohort, list) and cohort and all(_text(x) for x in cohort), 'case_ids must be nonempty text array')
    _require(len(set(cohort)) == len(cohort) and set(cohort) <= ids, 'duplicate or unknown cohort case')
    ks = design['ks']
    _require(isinstance(ks, list) and ks and len(ks) <= 20, 'ks must be nonempty bounded array')
    _require(all(type(k) is int and 1 <= k <= MAX_K for k in ks), 'invalid k')
    _require(len(set(ks)) == len(ks), 'duplicate k')
    arms = design['arms']
    _require(isinstance(arms, dict) and 1 <= len(arms) <= 4 and all(_text(a) for a in arms), 'arms must have 1..4 names')
    for arm in arms.values():
        _object(arm, {'protocol', 'pins'}, {'protocol', 'pins'}, 'arm')
        _object(arm['pins'], set(PIN_FIELDS), set(PIN_FIELDS), 'arm pins')
    treatments = design['treatment_fields']
    _require(isinstance(treatments, list) and all(isinstance(x, str) for x in treatments), 'invalid treatment_fields')
    _require(len(set(treatments)) == len(treatments) and set(treatments) <= set(PIN_FIELDS) - {'rubric'}, 'invalid treatment_fields; rubric must be fixed')
    for left, right in combinations(arms.values(), 2):
        _require(all(left['pins'][p] == right['pins'][p] for p in PIN_FIELDS if p not in treatments), 'undeclared treatment difference')
    schedule = design['schedule']
    _require(isinstance(schedule, dict) and set(schedule) == set(cohort), 'schedule must cover fixed cohort exactly')
    expected = 0
    for slots in schedule.values():
        _require(isinstance(slots, list) and 1 <= len(slots) <= MAX_K, 'invalid repeat schedule length')
        repeats = set()
        for slot in slots:
            fields = {'repeat_id', 'seed', 'order'}
            _object(slot, fields, fields, 'schedule slot')
            _require(_text(slot['repeat_id']) and slot['repeat_id'] not in repeats, 'duplicate or missing scheduled repeat_id')
            repeats.add(slot['repeat_id'])
            _require(slot['seed'] is None or type(slot['seed']) is int, 'seed must be integer or null')
            _require(isinstance(slot['order'], list) and len(slot['order']) == len(arms) and all(_text(x) for x in slot['order']) and set(slot['order']) == set(arms), 'order must be an arm permutation')
        expected += len(slots) * len(arms)
    _require(expected <= MAX_TRIALS, 'planned trial limit exceeded')
    delta = design['practical_delta']
    _require(delta is None or (type(delta) in (int, float) and 0 <= delta <= 1), 'practical_delta must be null or in [0,1]')
    boot = design['bootstrap']
    _object(boot, {'version', 'seed', 'resamples'}, {'version', 'seed', 'resamples'}, 'bootstrap')
    _require(boot['version'] == BOOT_VERSION and type(boot['seed']) is int, 'unsupported bootstrap version or seed')
    _require(type(boot['resamples']) is int and 100 <= boot['resamples'] <= 2000, 'bootstrap resamples must be 100..2000')
    _require(boot['resamples'] * len(cohort) * len(ks) * (len(arms) + math.comb(len(arms), 2)) <= MAX_BOOT_WORK, 'bootstrap work limit exceeded')
    reasons = []
    core = {k: v for k, v in design.items() if k != 'manifest'}
    if evidence.json(design['manifest']) != core:
        reasons.append('design_manifest_unavailable_or_mismatch')
    for name, arm in sorted(arms.items()):
        if evidence.json(arm['protocol']) != arm['pins']:
            reasons.append(f'{name}:protocol_manifest_unavailable_or_mismatch')
        if any(evidence.text(pin) is None for pin in arm['pins'].values()):
            reasons.append(f'{name}:protocol_pins_unavailable')
    return sorted(ks), sorted(arms), expected, reasons


def _trial_reasons(trial, row, arm, slot, design, evidence):
    reasons = []
    group = row.get('grouping') if isinstance(row.get('grouping'), dict) else {}
    expected = {
        'cohort_id': design['cohort_id'], 'case_sha256': row.get('content_sha256'),
        'dataset_version': row.get('dataset_version'), 'group_id': group.get('group_id'),
        'root_cause_id': group.get('root_cause_id'), 'protocol': arm['protocol'],
        'pins': arm['pins'], 'input': row.get('input'), 'source_context': row.get('source_context'),
        'seed': slot['seed'], 'order': slot['order'].index(trial['arm']),
    }
    for field, value in expected.items():
        if _canonical(trial.get(field)) != _canonical(value) or value is None:
            reasons.append(f'{field}_mismatch_or_unknown')
    if row.get('expected_output_or_rubric') != arm['pins']['rubric']:
        reasons.append('rubric_mismatch')
    source_manifest = evidence.json(arm['pins']['source'])
    if not isinstance(source_manifest, dict) or not isinstance(source_manifest.get('sources'), list) or row.get('source') not in source_manifest['sources']:
        reasons.append('source_manifest_mismatch')
    binding = {k: v for k, v in trial.items() if k not in ('execution', 'oracle', 'usage', 'cost')}
    execution = evidence.json(trial.get('execution'))
    executed = isinstance(execution, dict) and execution.get('status') == 'executed' and execution.get('trial') == binding
    if not executed:
        reasons.append('execution_unavailable_or_not_executed')
    oracle = evidence.json(trial.get('oracle'))
    outcome = None
    if not isinstance(oracle, dict):
        reasons.append('oracle_unavailable')
        return sorted(set(reasons)), outcome
    expected_oracle = {
        'trial_id': trial['trial_id'],
        'execution_sha256': trial['execution'].get('sha256') if isinstance(trial.get('execution'), dict) else None,
        'case_sha256': row.get('content_sha256'),
        'rubric_sha256': row['expected_output_or_rubric'].get('sha256') if isinstance(row.get('expected_output_or_rubric'), dict) else None,
        'independent_label_sha256': row['independent_label'].get('sha256') if isinstance(row.get('independent_label'), dict) else None,
    }
    if any(value is None or oracle.get(k) != value for k, value in expected_oracle.items()):
        reasons.append('oracle_binding_mismatch')
    checker = oracle.get('checker')
    if not isinstance(checker, dict) or checker.get('kind') not in ('independent_human', 'deterministic') or evidence.text(checker.get('evidence')) is None:
        reasons.append('independent_checker_unavailable')
    checks = oracle.get('checks')
    if not isinstance(checks, list) or not checks or not all(isinstance(c, dict) and _text(c.get('kind')) for c in checks):
        reasons.append('goal_checks_unavailable')
    else:
        if not {'final_goal', 'forbidden_effect'} <= {c.get('kind') for c in checks}:
            reasons.append('required_goal_checks_missing')
        if any(c.get('status') not in ('pass', 'fail') or evidence.text(c.get('evidence')) is None for c in checks):
            reasons.append('goal_checks_unavailable')
        derived = 'fail' if any(c.get('status') == 'fail' for c in checks) else 'pass'
        if oracle.get('outcome') not in ('pass', 'fail') or oracle['outcome'] != derived:
            reasons.append('outcome_unknown_or_conflicting')
    if not reasons:
        outcome = oracle['outcome']
    return sorted(set(reasons)), outcome


def _clusters(rows):
    """Connected closure of declared task/root/group identities; never split a root."""
    parent = {r['case_id']: r['case_id'] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen = {}
    for row in rows:
        for field in ('group_id', 'root_cause_id', 'canonical_task_id'):
            key = (field, row[field])
            if key in seen:
                a, b = sorted((find(row['case_id']), find(seen[key])))
                parent[b] = a
            seen[key] = row['case_id']
    groups = defaultdict(list)
    for row in rows:
        groups[find(row['case_id'])].append(row)
    return [sorted(g, key=lambda r: r['case_id']) for _, g in sorted(groups.items())]


def _mean(rows, arm, k, metric):
    return math.fsum(r['arms'][arm]['metrics'][str(k)][metric] for r in rows) / len(rows) if rows else None


def _descriptive(rows, arms, ks):
    """Case-weighted summaries with paired deltas; no subgroup uncertainty claim."""
    return {
        'case_count': len(rows), 'case_ids': [r['case_id'] for r in rows],
        'arms': {arm: {str(k): {m: _mean(rows, arm, k, m) for m in ('pass_at_k', 'pass_pow_k')}
                       for k in ks} for arm in arms},
        'paired': [{'left': left, 'right': right, 'direction': 'right_minus_left',
                    'metrics': {str(k): {m: math.fsum(
                        r['arms'][right]['metrics'][str(k)][m] - r['arms'][left]['metrics'][str(k)][m]
                        for r in rows) / len(rows) for m in ('pass_at_k', 'pass_pow_k')}
                                for k in ks}} for left, right in combinations(arms, 2)],
    }


def _bootstrap(rows, arms, ks, config):
    clusters = _clusters(rows)
    strata = defaultdict(list)
    mixed = False
    for cluster in clusters:
        names = {r['stratum'] for r in cluster}
        if len(names) != 1:
            mixed = True
        else:
            strata[next(iter(names))].append(cluster)
    support = {name: {'clusters': len(gs), 'cases': sum(map(len, gs))} for name, gs in sorted(strata.items())}
    reason = ('cross_stratum_cluster' if mixed else 'insufficient_clusters' if len(clusters) < 4 or any(len(gs) < 3 for gs in strata.values()) else None)
    result = {'version': BOOT_VERSION, 'seed': config['seed'], 'resamples': config['resamples'],
              'cluster_count': len(clusters), 'strata': support, 'status': reason or 'available',
              'scope': 'conditional supplied cohort cluster percentile; no population or simultaneous coverage guarantee',
              'cluster_members': [[r['case_id'] for r in g] for g in clusters]}
    draws = []
    if reason is None:
        keys = [(a, k, m) for a in arms for k in ks for m in ('pass_at_k', 'pass_pow_k')]
        # Summarize each intact cluster once. Large clusters cannot multiply the
        # work by being drawn repeatedly; n and all arm sums travel together.
        summaries = {
            name: [(len(group), {key: math.fsum(
                r['arms'][key[0]]['metrics'][str(key[1])][key[2]] for r in group
            ) for key in keys}) for group in groups]
            for name, groups in strata.items()
        }
        # Counter-based SHA-256 stream + rejection avoids platform PRNG/version drift.
        counter = 0

        def index(n):
            nonlocal counter
            limit = 2**256 - (2**256 % n)
            while True:
                payload = f'{BOOT_VERSION}\0{config["seed"]}\0{counter}'.encode('utf-8')
                counter += 1
                value = int.from_bytes(hashlib.sha256(payload).digest(), 'big')
                if value < limit:
                    return value % n

        for _ in range(config['resamples']):
            draw = {}
            for name, groups in sorted(summaries.items()):
                selected = [groups[index(len(groups))] for _ in groups]
                denominator = sum(n for n, _ in selected)
                share = support[name]['cases'] / len(rows)
                for key in keys:
                    value = math.fsum(sums[key] for _, sums in selected) / denominator
                    draw[key] = draw.get(key, 0.0) + share * value
            draws.append(draw)
    return result, draws


def _interval(values, reason):
    if reason != 'available':
        return {'status': reason, 'interval_95': None}
    ordered = sorted(values)
    if not ordered or ordered[0] == ordered[-1]:
        return {'status': 'degenerate_bootstrap', 'interval_95': None}
    # Deterministic nearest-rank percentiles, versioned above.
    low = ordered[math.ceil(.025 * len(ordered)) - 1]
    high = ordered[math.ceil(.975 * len(ordered)) - 1]
    return {'status': 'available' if low < high else 'degenerate_percentiles',
            'interval_95': [low, high] if low < high else None}


def score(candidates, trials=None, *, design=None, artifacts=None):
    """Return conditional descriptive JSON measurements; malformed inputs raise ValueError.

    Evidence gaps withhold measurements rather than counting as failed trials.
    The report never certifies admission, human gold, source time or acceptance.
    """
    trials = [] if trials is None else trials
    artifacts = {} if artifacts is None else artifacts
    _bounded({'candidates': candidates, 'trials': trials, 'design': design, 'artifacts': artifacts})
    _require(isinstance(candidates, list) and len(candidates) <= MAX_CASES, 'candidates must be bounded array')
    _require(isinstance(trials, list) and len(trials) <= MAX_TRIALS, 'trials must be bounded array')
    _require(isinstance(artifacts, dict) and all(_text(k) and isinstance(v, str) for k, v in artifacts.items()), 'artifacts must map references to UTF-8 text')
    evidence, cases, candidate_reports = _Evidence(artifacts), {}, []
    for row in candidates:
        _require(isinstance(row, dict) and _text(row.get('candidate_id')), 'candidate_id required')
        cid = row['candidate_id']
        _require(cid not in cases, 'duplicate candidate_id')
        _require(_text(row.get('dataset_version')), 'dataset_version required')
        cases[cid] = row
        reasons = _candidate_reasons(row, evidence)
        candidate_reports.append({'case_id': cid, 'reasons': reasons})
    report = {
        'schema_version': 'evalops.score-reliability.v1', 'canon_version': '0.26.2',
        'status': 'needs_labels' if any('needs_labels' in r['reasons'] for r in candidate_reports) else 'unavailable',
        'quality_acceptance': 'not_evaluated', 'external_acceptance': 'unknown',
        'source_time_and_predeclaration': 'unavailable', 'evidence_authenticity': 'unavailable',
        'estimate_scope': 'case-macro descriptive on fixed complete supplied-evidence intersection',
        'population': {'status': 'unavailable', 'estimate': None,
                       'reason': 'No population design inference implemented; frame/weights never inferred'},
        'historical_review_verdict_consistency': {'status': 'not_evaluated', 'value': None},
        'dispatch_infrastructure': {'status': 'not_evaluated', 'counts': {}},
        'runtime_task_reliability': {'status': 'unavailable', 'reason': 'No controlled task reliability established by current supplied candidates'},
        'candidate_coverage': {'records': len(cases), 'needs_labels': sum('needs_labels' in r['reasons'] for r in candidate_reports),
                               'unavailable': sum(bool(r['reasons']) for r in candidate_reports)},
        'candidates': sorted(candidate_reports, key=lambda r: r['case_id']),
        'attempts': [], 'cohort': None, 'arms': {}, 'paired': [], 'uncertainty': None,
        'grouped': [], 'strata': {},
        'economics': {'usage': None, 'cost': None, 'status': 'unavailable'},
        'limitations': [
            'Supplied hashes bind bytes, not source-time, independence, truth, completeness or predeclaration.',
            'All dataset-v1 candidates are quarantined; historical assisted human presentations are not gold.',
            'No execution, production trials, population inference, faithfulness evaluation or native acceptance is performed.',
            'Excluded cases are disclosed; estimates do not describe the incomplete declared cohort.',
        ],
    }
    if design is None:
        _require(not trials, 'trials require explicit fixed design')
        return report
    ks, arms, expected_count, design_reasons = _design(design, set(cases), evidence)
    lookup, trial_ids = {}, set()
    attempt_reports = []
    for trial in trials:
        _object(trial, {'trial_id', 'case_id', 'arm', 'repeat_id'}, TRIAL_FIELDS, 'trial')
        _require(all(_text(trial[k]) for k in ('trial_id', 'case_id', 'arm', 'repeat_id')), 'trial identity fields required')
        _require(trial['trial_id'] not in trial_ids, 'duplicate trial_id')
        trial_ids.add(trial['trial_id'])
        cid, arm, repeat = trial['case_id'], trial['arm'], trial['repeat_id']
        _require(cid in design['case_ids'] and arm in arms, 'trial outside declared cohort/arm')
        slots = {s['repeat_id']: s for s in design['schedule'][cid]}
        _require(repeat in slots, 'trial outside repeat schedule; retain extra attempts by versioning design')
        key = (cid, arm, repeat)
        _require(key not in lookup, 'duplicate case/arm/repeat attempt')
        reasons, outcome = _trial_reasons(trial, cases[cid], design['arms'][arm], slots[repeat], design, evidence)
        execution = evidence.json(trial.get('execution'))
        execution_status = execution.get('status') if isinstance(execution, dict) else None
        if execution_status not in ('executed', 'dispatch_refused', 'not_executed', 'unknown'):
            execution_status = 'unavailable'
        result = {'trial_id': trial['trial_id'], 'case_id': cid, 'arm': arm, 'repeat_id': repeat,
                  'status': 'available' if not reasons else 'unavailable', 'outcome': outcome,
                  'execution_status': execution_status,
                  'reasons': reasons, 'usage': copy.deepcopy(trial.get('usage')), 'cost': copy.deepcopy(trial.get('cost'))}
        lookup[key] = result
        attempt_reports.append(result)
    eligible, excluded = [], []
    candidate_reasons = {r['case_id']: r['reasons'] for r in candidate_reports}
    missing = []
    for cid in sorted(design['case_ids']):
        row, slots = cases[cid], design['schedule'][cid]
        reasons = list(candidate_reasons[cid]) + design_reasons
        if len(slots) < max(ks):
            reasons.append('insufficient_scheduled_trials_for_all_k')
        per_arm = {}
        for arm in arms:
            attempts = []
            for slot in slots:
                key = (cid, arm, slot['repeat_id'])
                if key not in lookup:
                    missing.append({'case_id': cid, 'arm': arm, 'repeat_id': slot['repeat_id']})
                    reasons.append('missing_planned_attempt')
                else:
                    attempts.append(lookup[key])
                    if lookup[key]['reasons']:
                        reasons.append('unavailable_attempt')
            c = sum(a['outcome'] == 'pass' for a in attempts)
            complete = len(attempts) == len(slots) and all(a['outcome'] in ('pass', 'fail') for a in attempts)
            per_arm[arm] = {'n': len(slots), 'observed_attempts': len(attempts),
                            'successes': c if complete else None,
                            'failures': len(slots) - c if complete else None,
                            'metrics': {str(k): pass_metrics(len(slots), c, k) for k in ks} if complete and len(slots) >= max(ks) else None}
        if reasons:
            for values in per_arm.values():
                values['metrics'] = None
            excluded.append({'case_id': cid, 'reasons': sorted(set(reasons)), 'arms': per_arm})
        else:
            group = row['grouping']
            eligible.append({'case_id': cid, 'group_id': group['group_id'], 'root_cause_id': group['root_cause_id'],
                             'canonical_task_id': group['canonical_task_id'], 'stratum': row['stratum'], 'arms': per_arm})
    # Compute linkage on the entire declared cohort. A missing case can be a
    # bridge between roots, so complete-case filtering must not split closure.
    linked = []
    for cid in sorted(design['case_ids']):
        group = cases[cid].get('grouping')
        if isinstance(group, dict) and all(_text(group.get(k)) for k in ('group_id', 'root_cause_id', 'canonical_task_id')):
            linked.append({'case_id': cid, **{k: group[k] for k in ('group_id', 'root_cause_id', 'canonical_task_id')}})
    blocked = {r['case_id'] for r in excluded}
    propagated = set()
    for cluster in _clusters(linked):
        members = {r['case_id'] for r in cluster}
        if members & blocked:
            propagated.update(members - blocked)
    retained = []
    for row in eligible:
        if row['case_id'] in propagated:
            unavailable_arms = copy.deepcopy(row['arms'])
            for value in unavailable_arms.values():
                value['metrics'] = None
            excluded.append({'case_id': row['case_id'], 'reasons': ['linked_case_unavailable'], 'arms': unavailable_arms})
        else:
            retained.append(row)
    eligible = retained
    excluded.sort(key=lambda r: r['case_id'])
    report['attempts'] = sorted(attempt_reports, key=lambda r: (r['case_id'], r['arm'], r['repeat_id']))
    report['dispatch_infrastructure'] = {
        'status': 'supplied_record_counts_only',
        'counts': {state: sum(r['execution_status'] == state for r in attempt_reports)
                   for state in ('executed', 'dispatch_refused', 'not_executed', 'unknown', 'unavailable')},
    }
    report['cohort'] = {
        'cohort_id': design['cohort_id'], 'ks': ks, 'declared_cases': len(design['case_ids']),
        'eligible_cases': len(eligible), 'case_coverage': len(eligible) / len(design['case_ids']),
        'expected_attempts': expected_count, 'supplied_attempts': len(trials),
        'missing_attempts': missing, 'unavailable_attempts': sum(a['status'] == 'unavailable' for a in attempt_reports),
        'excluded': excluded, 'per_case': eligible, 'design_reasons': design_reasons,
        'denominator_policy': 'same complete case intersection for all arms and all requested k',
    }
    boot, draws = _bootstrap(eligible, arms, ks, design['bootstrap'])
    report['uncertainty'] = boot
    report['grouped'] = [_descriptive(cluster, arms, ks) for cluster in _clusters(eligible)]
    for name in sorted({r['stratum'] for r in eligible}):
        report['strata'][name] = _descriptive([r for r in eligible if r['stratum'] == name], arms, ks)
    for arm in arms:
        report['arms'][arm] = {}
        for k in ks:
            report['arms'][arm][str(k)] = {
                metric: {'value': _mean(eligible, arm, k, metric), 'case_count': len(eligible),
                         **_interval([d[(arm, k, metric)] for d in draws], boot['status'])}
                for metric in ('pass_at_k', 'pass_pow_k')
            }
    for left, right in combinations(arms, 2):
        pair = {'left': left, 'right': right, 'direction': 'right_minus_left',
                'practical_delta': design['practical_delta'], 'case_count': len(eligible), 'metrics': {}, 'per_case': []}
        for row in eligible:
            pair['per_case'].append({'case_id': row['case_id'], 'metrics': {
                str(k): {m: row['arms'][right]['metrics'][str(k)][m] - row['arms'][left]['metrics'][str(k)][m]
                         for m in ('pass_at_k', 'pass_pow_k')} for k in ks}})
        for k in ks:
            pair['metrics'][str(k)] = {}
            for metric in ('pass_at_k', 'pass_pow_k'):
                values = [r['metrics'][str(k)][metric] for r in pair['per_case']]
                delta = math.fsum(values) / len(values) if values else None
                pair['metrics'][str(k)][metric] = {
                    'delta': delta, 'improved_cases': sum(v > 0 for v in values),
                    'tied_cases': sum(v == 0 for v in values), 'worsened_cases': sum(v < 0 for v in values),
                    'meets_practical_delta_descriptively': None if delta is None or design['practical_delta'] is None else delta >= design['practical_delta'],
                    **_interval([d[(right, k, metric)] - d[(left, k, metric)] for d in draws], boot['status']),
                }
        report['paired'].append(pair)
    if eligible:
        report['status'] = 'descriptive' if not excluded else 'partial_descriptive'
        report['runtime_task_reliability'] = {'status': 'descriptive', 'reason': 'Conditional supplied-evidence estimates; controlled production reliability and acceptance remain unknown'}
    report['economics'].update(
        supplied_attempts=len(trials), missing_planned_attempts=len(missing),
        missing_usage=sum(t.get('usage') is None for t in trials),
        missing_cost=sum(t.get('cost') is None for t in trials),
    )
    return report


def main(argv=None):
    """Strict bounded JSON in/out. Exit 0 exports unknowns too; exit 2 is I/O/schema error."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        with args.input.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        _require(len(raw) <= MAX_BYTES, 'input byte limit exceeded')
        request = _parse(raw.decode('utf-8'))
        _object(request, {'candidates'}, {'candidates', 'trials', 'design', 'artifacts'}, 'request')
        report = score(**request)
        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            _require(args.output.resolve() != args.input.resolve() and not (
                args.output.exists() and args.output.samefile(args.input)), 'output must not overwrite input')
            args.output.write_text(serialized, encoding='utf-8')
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError, OverflowError) as exc:
        sys.stderr.write(json.dumps({'status': 'error', 'error': str(exc)}) + '\n')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
