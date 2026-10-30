"""Pure, bounded generation-support reporting; no retrieval or judge execution.

API: ``score(payload) -> dict``; CLI: ``--input FILE [--output FILE]`` (JSON).
No inputs are changed. Export success (exit 0) is not quality acceptance. Invalid
schema, duplicate keys, nonfinite numbers or resource limits raise ValueError
(CLI: structured stderr, exit 2). Only Python's standard library is used.

Input v1 is {schema_version: 'evalops.faithfulness-input.v1', cases: [...],
pairwise: [...]}. pairwise is optional. Each case entry has exactly:
  id: unique output/run ID (several outputs may share a frozen case),
  frozen_case: original dataset row, including its content_sha256,
  supplied_context: null or {text: string|null, references: [artifact_ref],
      freshness: current|stale|unknown, consistency: consistent|contradictory|unknown},
  generated_output: null or {text: string, claims: null|[{claim_id, text,
      citations: [reference strings]}], abstained: bool|null, fact_units: null|[strings]},
  judgment_protocol: null or protocol object,
  judgments: null or {claims: [{claim_id, label}], abstention: appropriate|
      inappropriate|unknown|null, provenance: object|null, qc: object|null},
  merge_only_contract: optional null or {kind: 'merge_only', artifact: artifact_ref,
      supplied_fact_units: [strings]}.
Artifact refs use dataset-v1's {ref, sha256, version}. Context sha256 covers exact
UTF-8 text. Case content_sha256 uses dataset-v1 canonical JSON, omitting only
content_sha256. Cases need candidate_id, dataset_version, input, source_context,
expected_output_or_rubric, execution_pins, source, protocol_sha256,
input_lock_sha256, content_sha256, status and schema_version. Additional frozen
fields are retained by the content hash. Candidate-v1 quarantine is immutable.
Nulls are allowed and reported, never borrowed from another run. Unknown major
versions are errors. A separate frozen export may use schema_version
'evalops.frozen-generation-case.v1', status 'frozen'; this is not admission to
dataset-v1, independent gold, a sealed split or a production episode.

Judgment protocols require prompt, model, rubric, decoding, seed, environment,
config, task_version, context, input_protocol and order_handling. Artifact pins
use artifact_ref; model uses dataset-v1 provider/model_id/revision. Missing/null
pins are unknown. Claims accept supported, unsupported, contradicted, conflicting,
abstention, unknown or null. Claims are EXTERNALLY enumerated observations; this
module neither extracts claims nor certifies that the inventory is exhaustive.
Unlisted claim judgments remain unknown; foreign/duplicate IDs are errors.

Provenance uses annotation's kind/exposure/attestation_ref/original_ref/
protocol_version/original_event_id plus source_time_evidence (artifact_ref).
QC optionally contains decisions [{decision_id,item_id,annotator,field,label,
 gold_label?,gold_ref?,repeat_of?}]. Gold/repeats are diagnostics per annotator
and field: >=20 each, >=10% each and >=.90 accuracy/agreement; repeat targets
must be original events for the same item/person/field. Non-null gold requires
an original artifact ref. These are supplied reference assertions, NOT gold
created or authenticated here. Retain original/pre-adjudication decisions.

There is deliberately NO trust-root or source-time authenticator in this pure
slice. A filename, role, attestation string, hash or 'verified' flag cannot prove
independence, authority or prior exposure. Even structurally complete human/QC
records only satisfy supplied-record diagnostics. All semantic labels stay
quarantined and accepted semantic rates unavailable until the external human
oracle/custodian verifies source-time provenance and scoped QC. Assisted and LLM
labels cannot become independent gold. No calibrated judge or quality acceptance
is claimed. Raw supplied distributions are explicitly diagnostic, over ALL
listed claims (including unknown/conflicting/quarantined), never semantic truth.
Missing claim inventories keep the total claim denominator and rates unknown.
Every output remains in output denominators, including missing outputs.

Pairwise entries: {pair_id, candidates: [case-entry IDs A,B], results: [...]};
result: {order: [A,B] or [B,A], winner: first|second|tie|abstention|unknown|null,
protocol: protocol|null, input_sha256: sha256|null}. input_sha256 binds canonical
{candidates: [{id, case_sha256, context_sha256, output_sha256}, ...]} in declared
candidate order. Hashes of output are canonical generated_output objects. Both
orders must be SUPPLIED with identical, complete protocols (order is outside the
protocol). Missing second order is incomplete. Case/context/input/pin mismatches
are retained separately; they never establish swapped execution. Consistency,
tie, inconsistency, abstention and unknown are raw result diagnostics, not judge
validation. All pairs and both expected order slots remain in denominators.

Mechanical citation resolution means only reference existence. Fact-unit subset
checks require the explicit merge_only_contract; fact units are opaque supplied
strings, never prose extracted here. Neither diagnostic establishes semantic
support, truth, required content or acceptable exact wording. Alternative outputs
remain legal; there is no string-match quality scorer or default merge-only rule.

Canon v0.26.2: [RAG-01] Evaluate retrieval and generation separately, [EVAL-11]
Open-ended tasks need the right scorer, [EVAL-12] Validate the judge against
humans, [EVAL-13] Pin the judging protocol (AI Engineering); [HITL-05] Agreement
is a diagnostic, not the truth (Human-in-the-Loop ML); [CAL-02] Unknown is a
valid result, [MLDATA-04] Persist data lineage (Designing Machine Learning
Systems); [PROV-01] Every output walks back to its evidence (Model Cards + AI
Engineering). Principles 13/15 and the context-obedience card motivate separate
stages, external evidence holds and denominators that retain difficult cases.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from collections import Counter, defaultdict

SCHEMA_VERSION = 'evalops.faithfulness.v1'
INPUT_VERSION = 'evalops.faithfulness-input.v1'
MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 100_000
MAX_DEPTH = 32
MAX_ITEMS = 10_000
MAX_CASES = 1_000
LABELS = ('supported', 'unsupported', 'contradicted', 'conflicting', 'abstention', 'unknown')
PIN_REFS = ('prompt', 'rubric', 'decoding', 'environment', 'config', 'context', 'input_protocol')
PIN_FIELDS = (*PIN_REFS, 'model', 'seed', 'task_version', 'order_handling')
CASE_FIELDS = set('schema_version candidate_id dataset_version input source_context '
                  'expected_output_or_rubric execution_pins source protocol_sha256 '
                  'input_lock_sha256 content_sha256 status'.split())


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _object(value, required, allowed, name):
    _require(type(value) is dict, f'{name}: expected object')
    _require(required <= value.keys(), f'{name}: missing fields {sorted(required - value.keys())}')
    _require(value.keys() <= allowed, f'{name}: unexpected fields {sorted(value.keys() - allowed)}')


def _bounded(value, depth=0, budget=None):
    if budget is None:
        budget = [MAX_NODES, MAX_BYTES]
    budget[0] -= 1
    _require(budget[0] >= 0 and depth <= MAX_DEPTH, 'JSON node/depth limit exceeded')
    if type(value) is dict:
        _require(len(value) <= MAX_ITEMS, 'object size limit exceeded')
        for key, child in value.items():
            _require(type(key) is str, 'JSON keys must be strings')
            _bounded(key, depth + 1, budget)
            _bounded(child, depth + 1, budget)
    elif type(value) is list:
        _require(len(value) <= MAX_ITEMS, 'array size limit exceeded')
        for child in value:
            _bounded(child, depth + 1, budget)
    elif type(value) is str:
        _require(len(value) <= 1_048_576, 'string size limit exceeded')
        try:
            budget[1] -= len(value.encode('utf-8'))
        except UnicodeError as exc:
            raise ValueError('invalid Unicode string') from exc
        _require(budget[1] >= 0, 'JSON byte limit exceeded')
    elif type(value) is float:
        _require(math.isfinite(value), 'numbers must be finite')
    elif type(value) is int:
        _require(value.bit_length() <= 128, 'integer size limit exceeded')
    else:
        _require(value is None or type(value) is bool, 'expected JSON value')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _ref(value):
    if value is None:
        return False
    _object(value, {'ref', 'sha256', 'version'}, {'ref', 'sha256', 'version'}, 'artifact')
    _require(_text(value['ref']) and _sha(value['sha256']), 'invalid artifact ref/hash')
    _require(value['version'] is None or _text(value['version']), 'invalid artifact version')
    return _text(value['version'])


def _protocol(value):
    value = {} if value is None else value
    _object(value, set(), set(PIN_FIELDS), 'judgment protocol')
    missing = []
    for key in PIN_FIELDS:
        pin = value.get(key)
        known = pin is not None
        if known and key in PIN_REFS:
            known = _ref(pin)
        elif known and key == 'model':
            _object(pin, {'provider', 'model_id', 'revision'},
                    {'provider', 'model_id', 'revision'}, 'model')
            _require(_text(pin['provider']) and _text(pin['model_id']), 'invalid model identity')
            _require(pin['revision'] is None or _text(pin['revision']), 'invalid model revision')
            known = _text(pin['revision'])
        elif known and key == 'seed':
            _require(type(pin) is int, 'seed must be integer or null')
        elif known:
            _require(_text(pin), f'{key} must be text or null')
        if not known:
            missing.append(key)
    return {'values': copy.deepcopy(value), 'unknown_fields': missing}


def _rate(numerator, denominator, *, complete=True):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator and complete else None,
            'status': 'supplied_diagnostic' if denominator and complete else 'unavailable'}


def _qc(qc):
    if qc is None:
        return {'status': 'unavailable', 'groups': []}
    _object(qc, {'decisions'}, {'decisions'}, 'qc')
    _require(type(qc['decisions']) is list, 'qc decisions must be array')
    events, groups, identities, gold_answers = {}, defaultdict(list), set(), {}
    required = {'decision_id', 'item_id', 'annotator', 'field', 'label'}
    for row in qc['decisions']:
        _object(row, required, required | {'gold_label', 'gold_ref', 'repeat_of'}, 'qc decision')
        _require(all(_text(row[k]) for k in required), 'invalid qc identity/label')
        _require(row['decision_id'] not in events, 'duplicate qc decision')
        gold, repeat = row.get('gold_label'), row.get('repeat_of')
        _require(gold is None or _text(gold), 'invalid gold label')
        _require(repeat is None or _text(repeat), 'invalid repeat link')
        _require(not (gold is not None and repeat is not None), 'repeat cannot also be gold')
        if gold is not None:
            _require(_ref(row.get('gold_ref')), 'gold requires versioned original reference')
            gold_key = (row['item_id'], row['field'])
            _require(gold_key not in gold_answers or gold_answers[gold_key] == gold,
                     'conflicting gold reference labels')
            gold_answers[gold_key] = gold
        elif row.get('gold_ref') is not None:
            raise ValueError('gold_ref without gold_label')
        identity = (row['item_id'], row['annotator'], row['field'])
        if repeat is None:
            _require(identity not in identities, 'duplicate original qc identity')
            identities.add(identity)
        events[row['decision_id']] = row
        groups[(row['annotator'], row['field'])].append(row)
    # Resolve links independently of JSON array order, retaining original events.
    for row in events.values():
        if row.get('repeat_of') is not None:
            original = events.get(row['repeat_of'])
            _require(original is not None and original is not row and original.get('repeat_of') is None,
                     'repeat must reference an original qc event')
            _require(all(original[k] == row[k] for k in ('item_id', 'annotator', 'field')),
                     'repeat item/annotator/field mismatch')
    summaries = []
    for (annotator, field), rows in sorted(groups.items()):
        gold = [r for r in rows if r.get('gold_label') is not None]
        repeats = [r for r in rows if r.get('repeat_of') is not None]
        correct = sum(r['label'] == r['gold_label'] for r in gold)
        consistent = sum(r['label'] == events[r['repeat_of']]['label'] for r in repeats)
        enough = len(gold) >= 20 and len(repeats) >= 20 and min(len(gold), len(repeats)) / len(rows) >= .10
        meets = enough and correct / len(gold) >= .90 and consistent / len(repeats) >= .90
        summaries.append({'annotator': annotator, 'field': field, 'decisions': len(rows),
                          'gold': _rate(correct, len(gold)), 'repeat': _rate(consistent, len(repeats)),
                          'status': 'supplied_thresholds_met' if meets else
                          'below_threshold' if enough else 'insufficient_support'})
    return {'status': 'supplied_thresholds_met' if summaries and all(
        r['status'] == 'supplied_thresholds_met' for r in summaries) else 'unavailable',
        'groups': summaries, 'decisions': copy.deepcopy(qc['decisions']),
        'source_authentication': 'unavailable'}


def _provenance(value):
    if value is None:
        return ['provenance_missing']
    fields = set('kind exposure attestation_ref original_ref protocol_version original_event_id '
                 'source_time_evidence'.split())
    _object(value, set(), fields, 'provenance')
    for key in fields - {'source_time_evidence'}:
        _require(value.get(key) is None or _text(value[key]), f'invalid provenance {key}')
    if value.get('source_time_evidence') is not None:
        _ref(value['source_time_evidence'])
    reasons = []
    if value.get('kind') not in ('blind_human', 'independent_expert'):
        reasons.append('not_independent_human')
    if value.get('exposure') != 'unexposed':
        reasons.append('exposure_not_unexposed')
    if any(value.get(k) is None for k in fields):
        reasons.append('provenance_incomplete')
    # Hashes and role claims do not authenticate source-time evidence or scoped authorization.
    reasons.append('source_time_and_authorization_unverified')
    return reasons


def _case(entry):
    required = {'id', 'frozen_case', 'supplied_context', 'generated_output',
                'judgment_protocol', 'judgments'}
    _object(entry, required, required | {'merge_only_contract'}, 'case entry')
    _require(_text(entry['id']), 'entry id must be text')
    case = entry['frozen_case']
    _require(type(case) is dict and CASE_FIELDS <= case.keys(), 'incomplete frozen case')
    _require(case['schema_version'] in ('evalops.real-case-candidate.v1',
                                       'evalops.frozen-generation-case.v1'), 'unsupported case version')
    _require(_text(case['candidate_id']) and _text(case['dataset_version']), 'invalid case identity')
    _require(case['status'] in ('frozen', 'quarantine'), 'invalid case status')
    if case['schema_version'] == 'evalops.real-case-candidate.v1':
        _require(case['status'] == 'quarantine' and case['dataset_version'] == '1.0.0',
                 'candidate-v1 cannot be promoted')
    for key in ('content_sha256', 'protocol_sha256', 'input_lock_sha256'):
        _require(_sha(case[key]), f'invalid case {key}')
    _require(case['content_sha256'] == _hash({k: v for k, v in case.items() if k != 'content_sha256'}),
             'frozen case content hash mismatch')
    missing = [k for k in ('input', 'source_context', 'expected_output_or_rubric') if case[k] is None]
    for key in ('input', 'source_context', 'expected_output_or_rubric'):
        if case[key] is not None:
            if not _ref(case[key]):
                missing.append(key + '.version')
    _require(case['source'] is None or type(case['source']) is dict, 'source must be object or null')
    source = case['source'] or {}
    for key in ('snapshot_sha256', 'row_sha256'):
        if source.get(key) is None:
            missing.append('source.' + key)
        else:
            _require(_sha(source[key]), f'invalid source {key}')
    pins = case['execution_pins']
    _require(pins is None or type(pins) is dict, 'execution_pins must be object or null')
    execution_fields = {'prompt', 'model', 'config', 'decoding', 'seed', 'environment',
                        'order_handling', 'task_version'}
    if pins is not None:
        _object(pins, set(), execution_fields, 'execution pins')
    unknown_execution = _protocol(pins)['unknown_fields']
    for key in sorted(execution_fields):
        if key in unknown_execution:
            missing.append('execution_pins.' + key)
    protocol = _protocol(entry['judgment_protocol'])
    context = entry['supplied_context']
    text, refs = None, []
    freshness, consistency = 'unknown', 'unknown'
    if context is not None:
        fields = {'text', 'references', 'freshness', 'consistency'}
        _object(context, fields, fields, 'context')
        text, refs = context['text'], context['references']
        _require(text is None or isinstance(text, str), 'context text must be string or null')
        _require(type(refs) is list, 'context references must be array')
        for ref in refs:
            _require(ref is not None, 'context reference cannot be null')
            _ref(ref)
        _require(len({r['ref'] for r in refs}) == len(refs), 'duplicate context reference')
        freshness, consistency = context['freshness'], context['consistency']
        _require(freshness in ('current', 'stale', 'unknown'), 'invalid freshness')
        _require(consistency in ('consistent', 'contradictory', 'unknown'), 'invalid consistency')
    context_hash = hashlib.sha256(text.encode('utf-8')).hexdigest() if text is not None else None
    binding = 'unknown' if context_hash is None or case['source_context'] is None else (
        'matched' if context_hash == case['source_context']['sha256'] else 'mismatch')
    output = entry['generated_output']
    claims, abstained = None, None
    if output is not None:
        fields = {'text', 'claims', 'abstained', 'fact_units'}
        _object(output, fields, fields, 'generated output')
        _require(isinstance(output['text'], str), 'output text must be string')
        claims, abstained = output['claims'], output['abstained']
        _require(abstained is None or type(abstained) is bool, 'abstained must be bool or null')
        _require(claims is None or type(claims) is list, 'claims must be array or null')
        seen = set()
        for claim in claims or []:
            _object(claim, {'claim_id', 'text', 'citations'}, {'claim_id', 'text', 'citations'}, 'claim')
            _require(_text(claim['claim_id']) and claim['claim_id'] not in seen, 'duplicate/invalid claim id')
            _require(_text(claim['text']), 'claim text must be nonempty')
            _require(type(claim['citations']) is list and all(_text(c) for c in claim['citations']),
                     'citations must be reference strings')
            seen.add(claim['claim_id'])
        if output['fact_units'] is not None:
            _units(output['fact_units'])
    judgments, labels = entry['judgments'], {}
    reasons, qc, abstention_label = ['needs_labels'], _qc(None), None
    if judgments is not None:
        fields = {'claims', 'abstention', 'provenance', 'qc'}
        _object(judgments, fields, fields, 'judgments')
        _require(type(judgments['claims']) is list, 'judgments claims must be array')
        known = {c['claim_id'] for c in claims or []}
        for row in judgments['claims']:
            _object(row, {'claim_id', 'label'}, {'claim_id', 'label'}, 'claim judgment')
            _require(_text(row['claim_id']) and row['claim_id'] in known and row['claim_id'] not in labels,
                     'foreign/duplicate claim judgment')
            _require(row['label'] is None or row['label'] in LABELS, 'invalid claim judgment label')
            labels[row['claim_id']] = row['label'] or 'unknown'
        abstention_label = judgments['abstention']
        _require(abstention_label in ('appropriate', 'inappropriate', 'unknown', None), 'invalid abstention label')
        reasons, qc = _provenance(judgments['provenance']), _qc(judgments['qc'])
        if qc['status'] != 'supplied_thresholds_met':
            reasons.append('qc_unavailable')
    if case['status'] == 'quarantine':
        reasons.append('dataset_quarantine')
    if missing or protocol['unknown_fields']:
        reasons.append('pins_incomplete')
    if binding != 'matched':
        reasons.append('context_binding_' + binding)
    for field, expected in (('context', context_hash), ('rubric', (
            case['expected_output_or_rubric'] or {}).get('sha256')),
            ('input_protocol', case['protocol_sha256'])):
        pin = protocol['values'].get(field)
        if pin is not None and expected is not None and pin['sha256'] != expected:
            reasons.append('judgment_' + field + '_mismatch')
    reference_ids = {r['ref'] for r in refs}
    observations = []
    for claim in claims or []:
        citations = claim['citations']
        label = labels.get(claim['claim_id'], 'unknown')
        observations.append({'claim_id': claim['claim_id'], 'supplied_label': label,
                             'semantic_status': 'quarantined' if label != 'unknown' else 'needs_labels',
                             'citations': {'count': len(citations),
                                           'resolved': sum(c in reference_ids for c in citations),
                                           'unresolved': [c for c in citations if c not in reference_ids]}})
    return {'id': entry['id'], 'candidate_id': case['candidate_id'],
            'status': 'needs_labels' if not any(v != 'unknown' for v in labels.values()) and
                      abstention_label in (None, 'unknown') else 'quarantined',
            'case_sha256': case['content_sha256'], 'dataset_version': case['dataset_version'],
            'dataset_status': case['status'], 'protocol_sha256': case['protocol_sha256'],
            'input_lock_sha256': case['input_lock_sha256'], 'source': copy.deepcopy(case['source']),
            'case_refs': {k: copy.deepcopy(case[k]) for k in
                          ('input', 'source_context', 'expected_output_or_rubric')},
            'execution_pins': copy.deepcopy(pins), 'missing_case_pins': missing,
            'judgment_protocol': protocol, 'context_sha256': context_hash,
            'output_sha256': _hash(output) if output is not None else None,
            'context': {'availability': 'missing' if text is None else 'present',
                        'freshness': freshness, 'consistency': consistency,
                        'observations_authority': 'supplied_not_authenticated', 'binding': binding},
            'output_status': 'missing' if output is None else 'present',
            'claim_denominator': None if claims is None else len(claims),
            'claim_inventory_completeness': 'unverified', 'claims': observations,
            'abstention': {'supplied_behavior': abstained, 'supplied_judgment': abstention_label,
                           'semantic_status': 'unavailable'},
            'quarantine_reasons': sorted(set(reasons)), 'qc': qc,
            'mechanical_facts': _facts(entry.get('merge_only_contract'), output),
            'usage': None, 'cost': None}


def _units(value):
    _require(type(value) is list and all(_text(u) for u in value), 'fact units must be array of strings')
    _require(len(set(value)) == len(value), 'duplicate fact unit')


def _facts(contract, output):
    if contract is None:
        return {'status': 'not_evaluated', 'subset': None, 'denominator': None}
    fields = {'kind', 'artifact', 'supplied_fact_units'}
    _object(contract, fields, fields, 'merge-only contract')
    _require(contract['kind'] == 'merge_only' and _ref(contract['artifact']), 'invalid merge-only contract')
    _units(contract['supplied_fact_units'])
    units = output['fact_units'] if output is not None else None
    if units is None:
        return {'status': 'unavailable', 'subset': None, 'denominator': None}
    outside = sorted(set(units) - set(contract['supplied_fact_units']))
    return {'status': 'mechanical_only', 'subset': not outside, 'denominator': len(units),
            'outside_supplied_units': outside, 'contract': copy.deepcopy(contract['artifact'])}


def _pairwise(rows, cases):
    _require(type(rows) is list and len(rows) <= MAX_CASES, 'pairwise must be bounded array')
    reports, seen = [], set()
    for pair in rows:
        fields = {'pair_id', 'candidates', 'results'}
        _object(pair, fields, fields, 'pair')
        _require(_text(pair['pair_id']) and pair['pair_id'] not in seen, 'duplicate/invalid pair id')
        seen.add(pair['pair_id'])
        ids = pair['candidates']
        _require(type(ids) is list and len(ids) == 2 and all(_text(i) and i in cases for i in ids)
                 and ids[0] != ids[1], 'pair requires two distinct known output ids')
        expected = _hash({'candidates': [{k: cases[i][k] for k in
                          ('id', 'case_sha256', 'context_sha256', 'output_sha256')} for i in ids]})
        _require(type(pair['results']) is list and len(pair['results']) <= 2, 'pair results must have <=2 orders')
        orders, observations, problems = {}, [], []
        left, right = (cases[i] for i in ids)
        if left['case_sha256'] != right['case_sha256'] or left['context_sha256'] != right['context_sha256']:
            problems.append('case_or_context_mismatch')
        if any(c['output_sha256'] is None or c['context_sha256'] is None for c in (left, right)):
            problems.append('missing_output_or_context')
        for result in pair['results']:
            fields = {'order', 'winner', 'protocol', 'input_sha256'}
            _object(result, fields, fields, 'pair result')
            order = result['order']
            _require(order == ids or order == ids[::-1], 'invalid pair order')
            key = tuple(order)
            _require(key not in orders, 'duplicate pair order')
            winner = result['winner']
            _require(winner in ('first', 'second', 'tie', 'abstention', 'unknown', None), 'invalid pair winner')
            pin = _protocol(result['protocol'])
            _require(result['input_sha256'] is None or _sha(result['input_sha256']), 'invalid pair input hash')
            if result['input_sha256'] != expected:
                problems.append('input_binding_unknown' if result['input_sha256'] is None else 'input_binding_mismatch')
            if pin['unknown_fields']:
                problems.append('protocol_incomplete')
            context_pin = pin['values'].get('context')
            if context_pin is not None and left['context_sha256'] is not None and (
                    context_pin['sha256'] != left['context_sha256']):
                problems.append('protocol_context_mismatch')
            rubric_pin = pin['values'].get('rubric')
            rubric = left['case_refs']['expected_output_or_rubric']
            if rubric_pin is not None and rubric is not None and rubric_pin['sha256'] != rubric['sha256']:
                problems.append('protocol_rubric_mismatch')
            input_pin = pin['values'].get('input_protocol')
            if input_pin is not None and input_pin['sha256'] != left['protocol_sha256']:
                problems.append('protocol_input_protocol_mismatch')
            canonical = order[0 if winner == 'first' else 1] if winner in ('first', 'second') else winner or 'unknown'
            orders[key] = (canonical, pin['values'])
            observations.append({'order': list(order), 'winner': winner, 'canonical_winner': canonical,
                                 'protocol': pin, 'input_sha256': result['input_sha256']})
        if len(orders) == 2 and list(orders.values())[0][1] != list(orders.values())[1][1]:
            problems.append('protocol_mismatch')
        if len(orders) < 2:
            status = 'incomplete'
        elif problems:
            status = 'mismatch' if any('mismatch' in p for p in problems) else 'unknown'
        else:
            winners = [v[0] for v in orders.values()]
            status = ('unknown' if 'unknown' in winners else 'abstention' if 'abstention' in winners
                      else 'tie' if winners == ['tie', 'tie'] else
                      'consistent' if winners[0] == winners[1] else 'inconsistent')
        reports.append({'pair_id': pair['pair_id'], 'candidates': ids[:], 'status': status,
                        'expected_input_sha256': expected, 'expected_orders': 2, 'supplied_orders': len(orders),
                        'missing_orders': [o for o in (ids, ids[::-1]) if tuple(o) not in orders],
                        'problems': sorted(set(problems)), 'results': sorted(observations, key=lambda x: x['order'])})
    counts = {s: sum(p['status'] == s for p in reports) for s in
              ('consistent', 'tie', 'inconsistent', 'abstention', 'incomplete', 'mismatch', 'unknown')}
    return {'status': 'supplied_diagnostic' if rows else 'not_evaluated', 'pairs': reports,
            'counts': counts, 'pair_denominator': len(rows), 'expected_order_denominator': 2 * len(rows),
            'supplied_order_count': sum(p['supplied_orders'] for p in reports),
            'category_fractions': {s: _rate(n, len(rows)) for s, n in counts.items()},
            'order_disagreement': _rate(counts['inconsistent'], len(rows), complete=all(
                p['status'] in ('consistent', 'tie', 'inconsistent') for p in reports)),
            'execution': 'not_evaluated', 'judge_validation': 'unavailable'}


def score(payload):
    """Return deterministic diagnostics without mutation or semantic acceptance.

    See module documentation for the complete v1 wire contract and fixed bounds.
    Supplied distributions use all listed claims; null inventories withhold rates.
    Semantic success is NEVER derived from mechanical checks or pair agreement.
    """
    _bounded(payload)
    _require(len(_canonical(payload)) <= MAX_BYTES, 'JSON byte limit exceeded')
    _object(payload, {'schema_version', 'cases'}, {'schema_version', 'cases', 'pairwise'}, 'input')
    _require(payload['schema_version'] == INPUT_VERSION, 'unsupported input version')
    _require(type(payload['cases']) is list and len(payload['cases']) <= MAX_CASES, 'cases must be bounded array')
    reports, ids = [], set()
    for entry in payload['cases']:
        report = _case(entry)
        _require(report['id'] not in ids, 'duplicate output id')
        ids.add(report['id'])
        reports.append(report)
    reports.sort(key=lambda c: c['id'])
    counts = Counter(claim['supplied_label'] for c in reports for claim in c['claims'])
    listed = sum(len(c['claims']) for c in reports)
    unknown_inventories = sum(c['claim_denominator'] is None for c in reports)
    denominator = None if unknown_inventories else listed
    return {'schema_version': SCHEMA_VERSION, 'status': 'needs_labels' if not listed or all(
                c['status'] == 'needs_labels' for c in reports) else 'quarantined',
            'input_sha256': _hash(payload), 'stage': 'generation_support',
            'retrieval_ranking': {'status': 'not_evaluated'},
            'cases': reports,
            'coverage': {'output_denominator': len(reports),
                         'missing_outputs': sum(c['output_status'] == 'missing' for c in reports),
                         'listed_claims': listed, 'claim_denominator': denominator,
                         'outputs_with_unknown_claim_inventory': unknown_inventories,
                         'accepted_semantic_claims': 0,
                         'quarantined_claims': sum(claim['semantic_status'] == 'quarantined'
                                                   for c in reports for claim in c['claims']),
                         'needs_labels_claims': sum(claim['semantic_status'] == 'needs_labels'
                                                    for c in reports for claim in c['claims']),
                         'context': {axis: dict(sorted(Counter(c['context'][axis] for c in reports).items()))
                                     for axis in ('availability', 'freshness', 'consistency', 'binding')},
                         'abstention': {key: sum(c['abstention']['supplied_behavior'] is value for c in reports)
                                        for key, value in (('yes', True), ('no', False), ('unknown', None))}},
            'supplied_claim_distribution': {'status': 'unvalidated_diagnostic',
                'counts': {label: counts[label] for label in LABELS},
                'fractions': {label: _rate(counts[label], denominator,
                                          complete=denominator is not None) for label in LABELS}},
            'semantic_rates': {label: {'value': None, 'numerator': None, 'denominator': denominator,
                                      'status': 'unavailable'} for label in LABELS},
            'pairwise': _pairwise(payload.get('pairwise', []), {c['id']: c for c in reports}),
            'acceptance': {'independent_gold': 'needs_labels', 'judge_validation': 'unavailable',
                           'semantic_rates': 'unavailable', 'quality': 'not_evaluated',
                           'native_runtime': 'unavailable', 'production': 'unknown'},
            'usage': None, 'cost': None,
            'limitations': ['Supplied judgments, context status, fact units and claim inventories are not authenticated.',
                            'External source-time/authorization and scoped QC verification remains required.',
                            'No production rates, independent-episode counts, sealed splits, calibrated judge or live acceptance.',
                            'Raw distributions and pair agreement are diagnostics; citations/subsets are mechanical only.']}


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f'duplicate JSON key {key!r}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'invalid JSON constant {value}')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    temporary = None
    try:
        if args.output is not None:
            _require(args.input.resolve() != args.output.resolve() and not (
                args.output.exists() and args.input.samefile(args.output)), 'output must not overwrite input')
        with args.input.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        _require(len(raw) <= MAX_BYTES, 'JSON byte limit exceeded')
        payload = json.loads(raw.decode('utf-8'), object_pairs_hook=_json_object,
                             parse_constant=_invalid_constant)
        report = score(payload)
        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n'
        if args.output is not None:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=args.output.parent,
                                             prefix=f'.{args.output.name}.', delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(serialized)
            os.replace(temporary, args.output)
        sys.stdout.write(serialized)
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        sys.stderr.write(json.dumps({'schema_version': SCHEMA_VERSION, 'status': 'error', 'error': str(exc)}) + '\n')
        return 2
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
