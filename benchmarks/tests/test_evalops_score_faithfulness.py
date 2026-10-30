"""Synthetic unit observations only; no real labels, gold, trials or model calls."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / 'benchmarks/tools/evalops/score_faithfulness.py'
spec = importlib.util.spec_from_file_location('evalops_score_faithfulness', SCORER)
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def ref(name='synthetic-artifact', text=None):
    return {'ref': 'synthetic://' + name, 'version': 'synthetic-v1',
            'sha256': hashlib.sha256((text or name).encode()).hexdigest()}


def rehash(case):
    case['content_sha256'] = digest({k: v for k, v in case.items() if k != 'content_sha256'})


def protocol():
    return {**{k: ref(k) for k in ('prompt', 'rubric', 'decoding', 'environment', 'config',
                                  'context', 'input_protocol')},
            'model': {'provider': 'synthetic-provider', 'model_id': 'synthetic-judge', 'revision': 'v1'},
            'seed': 0, 'task_version': 'synthetic-v1', 'order_handling': 'both-orders-v1'}


def entry(name='synthetic-A', labels=('supported', 'unsupported', 'contradicted',
                                      'conflicting', 'abstention', 'unknown')):
    pins = protocol()
    context = 'Synthetic context, not production evidence.'
    case = {'schema_version': 'evalops.frozen-generation-case.v1',
            'candidate_id': 'synthetic-case', 'dataset_version': 'synthetic-v1', 'status': 'frozen',
            'input': ref('input'), 'source_context': ref('context', context),
            'expected_output_or_rubric': ref('rubric'),
            'execution_pins': {k: v for k, v in pins.items()
                               if k not in ('rubric', 'context', 'input_protocol')},
            'source': {'system': 'synthetic', 'snapshot_sha256': ref()['sha256'],
                       'row_sha256': ref('source-row')['sha256']},
            'protocol_sha256': ref('input_protocol')['sha256'],
            'input_lock_sha256': ref('input_lock')['sha256']}
    rehash(case)
    pins['context'] = copy.deepcopy(case['source_context'])
    return {'id': name, 'frozen_case': case,
            'supplied_context': {'text': context, 'references': [ref('source-1')],
                                 'freshness': 'current', 'consistency': 'consistent'},
            'generated_output': {'text': 'A synthetic answer with permitted alternative wording.',
                                 'claims': [{'claim_id': f'c{i}', 'text': f'Synthetic claim {i}',
                                             'citations': ['synthetic://source-1', 'synthetic://absent']}
                                            for i in range(len(labels))],
                                 'abstained': False, 'fact_units': ['synthetic-fact']},
            'judgment_protocol': pins,
            'judgments': {'claims': [{'claim_id': f'c{i}', 'label': label}
                                     for i, label in enumerate(labels)],
                          'abstention': 'unknown', 'provenance': None, 'qc': None}}


def payload(*entries, pairs=None):
    return {'schema_version': 'evalops.faithfulness-input.v1', 'cases': list(entries),
            'pairwise': pairs or []}


def pair(a, b, winners=('first', 'second'), pair_id='synthetic-pair'):
    binding = digest({'candidates': [
        {'id': e['id'], 'case_sha256': e['frozen_case']['content_sha256'],
         'context_sha256': hashlib.sha256(e['supplied_context']['text'].encode()).hexdigest(),
         'output_sha256': digest(e['generated_output'])} for e in (a, b)]})
    ids = [a['id'], b['id']]
    return {'pair_id': pair_id, 'candidates': ids,
            'results': [{'order': order, 'winner': winner, 'protocol': copy.deepcopy(a['judgment_protocol']),
                         'input_sha256': binding}
                        for order, winner in zip((ids[:], ids[::-1]), winners)]}


def synthetic_qc(wrong_gold=0, wrong_repeats=0):
    """Fabricated reference assertions for arithmetic tests, never a human gold set."""
    decisions = []
    for i in range(20):
        decisions.extend([
            {'decision_id': f'g{i}', 'item_id': f'synthetic-gold-{i}', 'annotator': 'synthetic-person',
             'field': 'support', 'label': 'unsupported' if i < wrong_gold else 'supported',
             'gold_label': 'supported', 'gold_ref': ref(f'synthetic-reference-{i}')},
            {'decision_id': f'o{i}', 'item_id': f'synthetic-repeat-{i}', 'annotator': 'synthetic-person',
             'field': 'support', 'label': 'supported'},
            {'decision_id': f'r{i}', 'item_id': f'synthetic-repeat-{i}', 'annotator': 'synthetic-person',
             'field': 'support', 'label': 'unsupported' if i < wrong_repeats else 'supported',
             'repeat_of': f'o{i}'}])
    return {'decisions': decisions}


def test_all_supplied_claim_categories_retain_denominator_without_truth_acceptance():
    report = scorer.score(payload(entry()))
    assert report['stage'] == 'generation_support'
    assert report['retrieval_ranking']['status'] == 'not_evaluated'
    assert report['status'] == 'quarantined'
    assert report['coverage']['output_denominator'] == 1
    assert report['coverage']['claim_denominator'] == 6
    raw = report['supplied_claim_distribution']
    assert list(raw['counts'].values()) == [1] * 6
    for category in raw['counts']:
        assert raw['fractions'][category]['value'] == pytest.approx(1 / 6)
        assert raw['fractions'][category]['denominator'] == 6
        assert report['semantic_rates'][category]['value'] is None
        assert report['semantic_rates'][category]['numerator'] is None
    assert report['coverage']['accepted_semantic_claims'] == 0
    assert report['acceptance']['quality'] == 'not_evaluated'
    assert report['usage'] is report['cost'] is None
    assert report['coverage']['quarantined_claims'] == 5
    assert report['coverage']['needs_labels_claims'] == 1


def test_missing_judgments_are_unknown_not_unsupported_or_successful():
    row = entry(labels=('supported', 'unsupported'))
    row['judgments'] = None
    report = scorer.score(payload(row))
    assert report['status'] == 'needs_labels'
    assert report['supplied_claim_distribution']['counts']['unknown'] == 2
    assert report['supplied_claim_distribution']['counts']['unsupported'] == 0
    assert report['semantic_rates']['supported']['value'] is None
    assert [c['semantic_status'] for c in report['cases'][0]['claims']] == ['needs_labels'] * 2


def test_partial_judgments_and_null_labels_stay_in_distribution():
    row = entry(labels=('supported', None, 'unsupported'))
    row['judgments']['claims'].pop()
    report = scorer.score(payload(row))
    assert report['supplied_claim_distribution']['counts']['unknown'] == 2
    assert report['supplied_claim_distribution']['fractions']['supported']['value'] == pytest.approx(1 / 3)
    assert report['coverage']['claim_denominator'] == 3


def test_missing_output_and_unknown_claim_inventory_do_not_become_zero_claims():
    a, b = entry('synthetic-A'), entry('synthetic-B')
    a['generated_output'] = None
    a['judgments'] = None
    b['generated_output']['claims'] = None
    b['judgments'] = None
    report = scorer.score(payload(a, b))
    assert report['coverage']['output_denominator'] == 2
    assert report['coverage']['missing_outputs'] == 1
    assert report['coverage']['claim_denominator'] is None
    assert report['coverage']['outputs_with_unknown_claim_inventory'] == 2
    assert all(r['value'] is None and r['denominator'] is None
               for r in report['supplied_claim_distribution']['fractions'].values())


def test_explicit_empty_claim_inventory_is_not_perfect_support():
    row = entry(labels=())
    row['generated_output']['abstained'] = True
    row['judgments']['abstention'] = 'appropriate'
    report = scorer.score(payload(row))
    assert report['coverage']['claim_denominator'] == 0
    assert report['coverage']['abstention'] == {'yes': 1, 'no': 0, 'unknown': 0}
    assert report['semantic_rates']['supported']['value'] is None
    assert report['cases'][0]['abstention']['semantic_status'] == 'unavailable'


def test_context_missing_stale_and_contradictory_are_separate_axes():
    missing, stale, conflict = (entry(f'synthetic-{i}', labels=('conflicting',)) for i in range(3))
    missing['supplied_context'] = None
    stale['supplied_context']['freshness'] = 'stale'
    conflict['supplied_context'].update(freshness='stale', consistency='contradictory')
    report = scorer.score(payload(missing, stale, conflict))
    context = report['coverage']['context']
    assert context['availability'] == {'missing': 1, 'present': 2}
    assert context['freshness'] == {'stale': 2, 'unknown': 1}
    assert context['consistency'] == {'consistent': 1, 'contradictory': 1, 'unknown': 1}
    assert report['coverage']['claim_denominator'] == 3
    assert report['supplied_claim_distribution']['counts']['conflicting'] == 3


def test_reference_existence_and_lexical_overlap_never_establish_support():
    row = entry(labels=('supported',))
    row['generated_output']['text'] = row['supplied_context']['text']
    row['judgments'] = None
    report = scorer.score(payload(row))
    claim = report['cases'][0]['claims'][0]
    assert claim['citations'] == {'count': 2, 'resolved': 1, 'unresolved': ['synthetic://absent']}
    assert claim['supplied_label'] == 'unknown'
    assert report['semantic_rates']['supported']['value'] is None


def test_fact_subset_requires_explicit_contract_and_does_not_grade_prose():
    row = entry(labels=())
    row['generated_output']['fact_units'] = ['synthetic-allowed', 'synthetic-new']
    assert scorer.score(payload(row))['cases'][0]['mechanical_facts']['status'] == 'not_evaluated'
    row['merge_only_contract'] = {'kind': 'merge_only', 'artifact': ref('synthetic-adoption'),
                                  'supplied_fact_units': ['synthetic-allowed']}
    report = scorer.score(payload(row))
    facts = report['cases'][0]['mechanical_facts']
    assert facts['subset'] is False
    assert facts['denominator'] == 2
    assert facts['outside_supplied_units'] == ['synthetic-new']
    row['generated_output']['fact_units'].pop()
    row['generated_output']['text'] = 'An alternative allowed path and wording.'
    report = scorer.score(payload(row))
    assert report['cases'][0]['mechanical_facts']['subset'] is True
    assert report['semantic_rates']['supported']['value'] is None
    row['generated_output']['fact_units'] = None
    assert scorer.score(payload(row))['cases'][0]['mechanical_facts']['subset'] is None


@pytest.mark.parametrize('kind', ['llm', 'user_assisted', 'post_review', 'independent_expert', 'blind_human'])
def test_role_attestation_and_even_full_supplied_qc_do_not_authenticate_source_time(kind):
    row = entry(labels=('supported',))
    row['judgments']['provenance'] = {
        'kind': kind, 'exposure': 'unexposed', 'attestation_ref': 'synthetic-claims-unexposed',
        'original_ref': 'synthetic-original', 'protocol_version': 'synthetic-v1',
        'original_event_id': 'synthetic-event', 'source_time_evidence': ref('synthetic-before-exposure')}
    row['judgments']['qc'] = synthetic_qc()
    report = scorer.score(payload(row))
    case = report['cases'][0]
    assert case['qc']['status'] == 'supplied_thresholds_met'
    assert case['qc']['source_authentication'] == 'unavailable'
    assert 'source_time_and_authorization_unverified' in case['quarantine_reasons']
    if kind in ('llm', 'user_assisted', 'post_review'):
        assert 'not_independent_human' in case['quarantine_reasons']
    assert report['semantic_rates']['supported']['value'] is None
    assert report['coverage']['accepted_semantic_claims'] == 0


def test_qc_arithmetic_scopes_and_pre_adjudication_records_retained():
    row = entry(labels=('supported',))
    qc = synthetic_qc(wrong_gold=2, wrong_repeats=3)
    row['judgments']['qc'] = qc
    report = scorer.score(payload(row))
    group = report['cases'][0]['qc']['groups'][0]
    assert group['decisions'] == 60
    assert group['gold']['value'] == pytest.approx(.90)
    assert group['gold']['denominator'] == 20
    assert group['repeat']['value'] == pytest.approx(.85)
    assert group['status'] == 'below_threshold'
    assert report['cases'][0]['qc']['decisions'] == qc['decisions']
    assert report['semantic_rates']['supported']['value'] is None


def test_qc_large_other_field_cannot_rescue_an_insufficient_field():
    row = entry()
    qc = synthetic_qc()
    qc['decisions'].append({'decision_id': 'small', 'item_id': 'synthetic-small',
                            'annotator': 'synthetic-person', 'field': 'abstention', 'label': 'unknown'})
    row['judgments']['qc'] = qc
    report = scorer.score(payload(row))['cases'][0]['qc']
    assert report['status'] == 'unavailable'
    assert [g['status'] for g in report['groups']] == ['insufficient_support', 'supplied_thresholds_met']


@pytest.mark.parametrize('change', ['duplicate_original', 'foreign_repeat', 'wrong_field', 'gold_repeat', 'missing_gold_ref'])
def test_qc_invalid_evidence_cannot_inflate_support(change):
    row = entry()
    qc = synthetic_qc()
    if change == 'duplicate_original':
        qc['decisions'].append({**qc['decisions'][0], 'decision_id': 'duplicate'})
    elif change == 'foreign_repeat':
        qc['decisions'][2]['repeat_of'] = 'absent'
    elif change == 'wrong_field':
        qc['decisions'][2]['field'] = 'abstention'
    elif change == 'gold_repeat':
        qc['decisions'][2].update(gold_label='supported', gold_ref=ref())
    else:
        qc['decisions'][0].pop('gold_ref')
    row['judgments']['qc'] = qc
    with pytest.raises(ValueError):
        scorer.score(payload(row))


def test_candidate_contract_is_never_promoted_and_unknown_pins_preserved():
    row = entry(labels=())
    case = row['frozen_case']
    case.update(schema_version='evalops.real-case-candidate.v1', dataset_version='1.0.0',
                status='quarantine', input=None, source_context=None, expected_output_or_rubric=None,
                execution_pins={k: None for k in case['execution_pins']}, independent_label=None,
                independent_gold_status='needs_labels', sealed_split=None,
                quarantine_reasons=['synthetic-missing-evidence'])
    rehash(case)
    row.update(supplied_context=None, generated_output=None, judgment_protocol=None, judgments=None)
    report = scorer.score(payload(row))
    assert report['cases'][0]['dataset_status'] == 'quarantine'
    assert report['cases'][0]['execution_pins'] == case['execution_pins']
    assert len(report['cases'][0]['missing_case_pins']) == 11
    assert report['cases'][0]['source'] == case['source']
    assert report['acceptance']['independent_gold'] == 'needs_labels'
    case['status'] = 'frozen'
    rehash(case)
    with pytest.raises(ValueError):
        scorer.score(payload(row))


def test_pairwise_canonical_identity_both_orders_and_hand_calculated_disagreement():
    a, b = entry(), entry('synthetic-B')
    rows = [pair(a, b, winners=w, pair_id=str(i)) for i, w in enumerate([
        ('first', 'second'), ('tie', 'tie'), ('first', 'first')])]
    report = scorer.score(payload(a, b, pairs=rows))['pairwise']
    assert [p['status'] for p in report['pairs']] == ['consistent', 'tie', 'inconsistent']
    assert report['order_disagreement'] == {
        'numerator': 1, 'denominator': 3, 'value': 1 / 3, 'status': 'supplied_diagnostic'}
    assert report['expected_order_denominator'] == report['supplied_order_count'] == 6
    assert report['execution'] == 'not_evaluated'
    assert report['judge_validation'] == 'unavailable'


def test_all_order_denominators_keep_abstention_unknown_missing_and_mismatch():
    a, b = entry(), entry('synthetic-B')
    winners = [('first', 'second'), ('tie', 'tie'), ('first', 'first'),
               ('abstention', 'second'), ('first',), ('first', 'second'), ('first', None)]
    rows = [pair(a, b, winners=w, pair_id=str(i)) for i, w in enumerate(winners)]
    rows[5]['results'][1]['protocol']['seed'] = 99
    report = scorer.score(payload(a, b, pairs=rows))['pairwise']
    assert list(report['counts'].values()) == [1] * 7
    assert report['pair_denominator'] == 7
    assert report['expected_order_denominator'] == 14
    assert report['supplied_order_count'] == 13
    assert report['pairs'][4]['missing_orders'] == [[b['id'], a['id']]]
    assert report['order_disagreement']['denominator'] == 7
    assert report['order_disagreement']['numerator'] == 1
    assert report['order_disagreement']['value'] is None
    assert sum(r['value'] for r in report['category_fractions'].values()) == pytest.approx(1)


@pytest.mark.parametrize('mode', ['null_protocol', 'missing_revision', 'input_unknown', 'input_changed',
                                  'context_changed', 'different_case', 'one_tie'])
def test_pairwise_mismatch_unknown_and_alternative_outcomes(mode):
    a, b = entry(), entry('synthetic-B')
    p = pair(a, b)
    expected = 'unknown'
    if mode == 'null_protocol':
        p['results'][1]['protocol'] = None
        expected = 'mismatch'
    elif mode == 'missing_revision':
        for r in p['results']:
            r['protocol']['model']['revision'] = None
    elif mode == 'input_unknown':
        p['results'][0]['input_sha256'] = None
    elif mode == 'input_changed':
        b['generated_output']['text'] = 'A different permitted answer; prior judgments are now stale.'
        expected = 'mismatch'
    elif mode == 'context_changed':
        b['supplied_context']['text'] = 'Changed synthetic context.'
        expected = 'mismatch'
    elif mode == 'different_case':
        b['frozen_case']['candidate_id'] = 'another-synthetic-case'
        rehash(b['frozen_case'])
        expected = 'mismatch'
    else:
        p['results'][0]['winner'] = 'tie'
        expected = 'inconsistent'
    report = scorer.score(payload(a, b, pairs=[p]))['pairwise']
    assert report['pairs'][0]['status'] == expected
    assert report['expected_order_denominator'] == 2


def test_empty_pair_is_incomplete_not_swapped_execution_and_empty_batch_is_unavailable():
    a, b = entry(), entry('synthetic-B')
    p = pair(a, b, winners=())
    report = scorer.score(payload(a, b, pairs=[p]))['pairwise']
    assert report['pairs'][0]['status'] == 'incomplete'
    assert report['supplied_order_count'] == 0
    assert report['order_disagreement']['value'] is None
    empty = scorer.score(payload())
    assert empty['status'] == 'needs_labels'
    assert empty['pairwise']['status'] == 'not_evaluated'
    assert empty['semantic_rates']['supported']['value'] is None


@pytest.mark.parametrize('mode', ['foreign_judgment', 'duplicate_judgment', 'foreign_pair', 'duplicate_order',
                                  'unknown_input_version', 'unknown_case_version', 'case_hash', 'extra_field',
                                  'nonfinite', 'deep', 'invalid_model', 'null_reference'])
def test_schema_and_bounded_unknown_handling(mode):
    a, b = entry(), entry('synthetic-B')
    data = payload(a, b)
    if mode == 'foreign_judgment':
        a['judgments']['claims'][0]['claim_id'] = 'absent'
    elif mode == 'duplicate_judgment':
        a['judgments']['claims'].append(copy.deepcopy(a['judgments']['claims'][0]))
    elif mode == 'foreign_pair':
        data['pairwise'] = [pair(a, b)]
        data['pairwise'][0]['candidates'][0] = 'absent'
    elif mode == 'duplicate_order':
        data['pairwise'] = [pair(a, b)]
        data['pairwise'][0]['results'][1]['order'] = [a['id'], b['id']]
    elif mode == 'unknown_input_version':
        data['schema_version'] = 'evalops.faithfulness-input.v2'
    elif mode == 'unknown_case_version':
        a['frozen_case']['schema_version'] = 'evalops.frozen-generation-case.v2'
        rehash(a['frozen_case'])
    elif mode == 'case_hash':
        a['frozen_case']['candidate_id'] = 'tampered'
    elif mode == 'extra_field':
        a['judgments']['provenance'] = {'verified': True}
    elif mode == 'nonfinite':
        a['judgment_protocol']['seed'] = float('nan')
    elif mode == 'deep':
        child = data
        for _ in range(40):
            child['deep'] = {}
            child = child['deep']
    elif mode == 'invalid_model':
        a['frozen_case']['execution_pins']['model'] = 'synthetic-unversioned-role'
        rehash(a['frozen_case'])
    else:
        a['supplied_context']['references'] = [None]
    with pytest.raises(ValueError):
        scorer.score(data)


def test_pure_function_deterministic_nonmutating_and_report_does_not_alias_inputs():
    a, b = entry(), entry('synthetic-B')
    data = payload(b, a, pairs=[pair(a, b)])
    original = copy.deepcopy(data)
    first, second = scorer.score(data), scorer.score(data)
    assert first == second
    assert data == original
    json.dumps(first, allow_nan=False)
    first['cases'][0]['source']['system'] = 'changed'
    first['cases'][0]['execution_pins']['model']['revision'] = 'changed'
    first['pairwise']['pairs'][0]['results'][0]['protocol']['values']['model']['revision'] = 'changed'
    assert data == original


@pytest.mark.parametrize('raw', ['{"schema_version":"x","schema_version":"y","cases":[]}',
                                  '{"schema_version":"x","cases":[],"number":NaN}',
                                  '{"schema_version":"x","cases":[],"number":Infinity}',
                                  '{"schema_version":"x","cases":[],"number":1e999}',
                                  '{"schema_version":"x","cases":[],"bad":"\\ud800"}',
                                  '[' * 1500 + ']' * 1500, 'invalid', '[]'])
def test_cli_strict_json_failures_preserve_existing_report(tmp_path, capsys, raw):
    source, output = tmp_path / 'synthetic-input.json', tmp_path / 'report.json'
    source.write_text(raw)
    output.write_text('previous report')
    assert scorer.main(['--input', str(source), '--output', str(output)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert json.loads(captured.err)['status'] == 'error'
    assert output.read_text() == 'previous report'


def test_cli_roundtrip_input_protection_and_finite_json(tmp_path, capsys):
    source, output = tmp_path / 'synthetic-input.json', tmp_path / 'report.json'
    data = payload(entry())
    source.write_text(json.dumps(data))
    assert scorer.main(['--input', str(source), '--output', str(output)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == json.loads(output.read_text()) == scorer.score(data)
    assert not captured.err
    for kind in ('same', 'symlink', 'hardlink'):
        target = source if kind == 'same' else tmp_path / kind
        if kind == 'symlink':
            target.symlink_to(source)
        elif kind == 'hardlink':
            target.hardlink_to(source)
        assert scorer.main(['--input', str(source), '--output', str(target)]) == 2
        capsys.readouterr()
        assert json.loads(source.read_text()) == data


def test_api_and_cli_resource_limits_are_enforced(tmp_path, capsys, monkeypatch):
    data = payload(entry())
    monkeypatch.setattr(scorer, 'MAX_CASES', 0)
    with pytest.raises(ValueError):
        scorer.score(data)
    monkeypatch.setattr(scorer, 'MAX_CASES', 1000)
    monkeypatch.setattr(scorer, 'MAX_BYTES', 64)
    source = tmp_path / 'synthetic-large.json'
    source.write_text(' ' * 65)
    assert scorer.main(['--input', str(source)]) == 2
    assert json.loads(capsys.readouterr().err)['status'] == 'error'
    with pytest.raises(ValueError):
        scorer.score(data)


def test_source_pin_and_context_binding_gaps_are_not_silently_repaired():
    row = entry()
    row['frozen_case']['source']['row_sha256'] = None
    row['frozen_case']['execution_pins']['model']['revision'] = None
    rehash(row['frozen_case'])
    row['supplied_context']['text'] = 'Changed context, not the pinned source.'
    report = scorer.score(payload(row))['cases'][0]
    assert 'source.row_sha256' in report['missing_case_pins']
    assert 'execution_pins.model' in report['missing_case_pins']
    assert report['context']['binding'] == 'mismatch'
    assert 'judgment_context_mismatch' in report['quarantine_reasons']


@pytest.mark.parametrize('field', ['context', 'rubric', 'input_protocol'])
def test_identical_but_wrong_pair_protocol_pins_do_not_pass_binding(field):
    a, b = entry(), entry('synthetic-B')
    p = pair(a, b)
    for result in p['results']:
        result['protocol'][field] = ref('wrong-synthetic-' + field)
    result = scorer.score(payload(a, b, pairs=[p]))['pairwise']['pairs'][0]
    assert result['status'] == 'mismatch'
    assert 'protocol_' + field + '_mismatch' in result['problems']
