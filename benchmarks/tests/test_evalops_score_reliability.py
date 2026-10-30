"""Offline unit checks using invented, explicitly synthetic evidence only.

These fixtures are not dataset admissions, human gold, production executions or
benchmark outcomes. Current dataset candidate checks below only assert a hold.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCORER = ROOT / 'benchmarks/tools/evalops/score_reliability.py'
SPEC = importlib.util.spec_from_file_location('evalops_score_reliability', SCORER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


class Synthetic:
    """In-memory protocol examples, never real trial/label material."""

    def __init__(self, outcomes, *, ks=(1, 2), groups=None, roots=None, strata=None):
        self.artifacts = {}
        self.serial = 0
        common = {field: self.artifact({'synthetic': field}) for field in MODULE.PIN_FIELDS}
        self.rubric = common['rubric']
        source_rows = [{'id': i, 'synthetic': 'invented unit fixture'} for i in range(len(outcomes))]
        snapshot = self.artifact(source_rows)
        self.sources = [{'system': 'synthetic-only', 'table': 'synthetic', 'source_id': i,
                         'snapshot': snapshot['ref'], 'snapshot_sha256': snapshot['sha256'],
                         'row_sha256': hashlib.sha256(canonical(row).encode('utf-8')).hexdigest()}
                        for i, row in enumerate(source_rows)]
        protocol_hash = self.artifact({'synthetic': 'dataset protocol'})['sha256']
        lock_hash = self.artifact({'synthetic': 'dataset input lock'})['sha256']
        common['source'] = self.artifact({'sources': self.sources})
        a = {'protocol': self.artifact(common), 'pins': common}
        bpins = copy.deepcopy(common)
        bpins['model'] = self.artifact({'synthetic': 'candidate-model-revision'})
        bpins['prompt'] = self.artifact({'synthetic': 'candidate-prompt-version'})
        b = {'protocol': self.artifact(bpins), 'pins': bpins}
        self.design = {
            'version': 'evalops.reliability-design.v1', 'cohort_id': 'SYNTHETIC-ONLY',
            'case_ids': [], 'ks': list(ks), 'arms': {'A': a, 'B': b},
            'treatment_fields': ['model', 'prompt'], 'schedule': {}, 'practical_delta': .1,
            'bootstrap': {'version': 'sha256-cluster-stratified/v1', 'seed': 7, 'resamples': 200},
        }
        self.candidates, self.trials = [], []
        for i, (left, right) in enumerate(outcomes):
            assert len(left) == len(right)
            cid = f'SYNTHETIC-case-{i}'
            self.design['case_ids'].append(cid)
            self.design['schedule'][cid] = [
                {'repeat_id': f'repeat-{j}', 'seed': 100 + j, 'order': ['A', 'B'] if j % 2 == 0 else ['B', 'A']}
                for j in range(len(left))
            ]
            row = {
                'candidate_id': cid, 'dataset_version': 'SYNTHETIC-unit-only-v2',
                'status': 'admitted', 'quarantine_reasons': [], 'independent_gold_status': 'available',
                'input': self.artifact({'synthetic': f'input-{i}'}),
                'source_context': self.artifact({'synthetic': f'context-{i}'}),
                'expected_output_or_rubric': self.rubric,
                'independent_label': self.artifact({'synthetic': 'NOT human gold', 'case': cid}),
                'grouping': {'canonical_task_id': f'task-{i}', 'group_id': groups[i] if groups else f'group-{i}',
                             'root_cause_id': roots[i] if roots else f'root-{i}', 'repeat_id': None,
                             'linkage_status': 'substantiated', 'evidence': [self.artifact({'synthetic': 'link'})]},
                'exposure': {'system_under_test': 'unexposed', 'attestation': self.artifact({'synthetic': 'exposure'})},
                'execution_pins': {
                    'prompt': common['prompt'], 'model': {'provider': 'synthetic', 'model_id': 'fake', 'revision': 'v1'},
                    'decoding': common['decoding'], 'seed': 100, 'environment': common['environment'],
                    'config': common['config'], 'order_handling': 'synthetic-counterbalanced', 'task_version': 'v1',
                },
                'protocol_sha256': protocol_hash, 'input_lock_sha256': lock_hash,
                'source': self.sources[i], 'track': 'synthetic-task',
                'stratum': strata[i] if strata else 'synthetic-stratum',
                'sampling': {'frame': None, 'population_weight': None, 'inclusion_probability': None, 'independent_episode': 'unknown'},
            }
            self.rehash(row)
            self.candidates.append(row)
            for arm, values in [('A', left), ('B', right)]:
                for j, outcome in enumerate(values):
                    slot = self.design['schedule'][cid][j]
                    trial = {
                        'trial_id': f'{cid}-{arm}-{j}', 'case_id': cid, 'arm': arm,
                        'repeat_id': slot['repeat_id'], 'seed': slot['seed'], 'order': slot['order'].index(arm),
                        'cohort_id': self.design['cohort_id'], 'case_sha256': row['content_sha256'],
                        'dataset_version': row['dataset_version'], 'group_id': row['grouping']['group_id'],
                        'root_cause_id': row['grouping']['root_cause_id'],
                        'protocol': self.design['arms'][arm]['protocol'], 'pins': self.design['arms'][arm]['pins'],
                        'input': row['input'], 'source_context': row['source_context'], 'usage': None, 'cost': None,
                    }
                    self.bind_trial(trial, row, outcome)
                    self.trials.append(trial)
        self.freeze()

    def artifact(self, value):
        self.serial += 1
        ref = f'synthetic-only:{self.serial}'
        text = canonical(value)
        self.artifacts[ref] = text
        return {'ref': ref, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'version': 'synthetic-v1'}

    def rehash(self, row):
        row.pop('content_sha256', None)
        row['content_sha256'] = hashlib.sha256(canonical(row).encode('utf-8')).hexdigest()

    def freeze(self):
        self.design.pop('manifest', None)
        self.design['manifest'] = self.artifact(self.design)

    def bind_trial(self, trial, row, outcome, status='executed'):
        binding = {k: v for k, v in trial.items() if k not in ('execution', 'oracle', 'usage', 'cost')}
        trial['execution'] = self.artifact({'trial': binding, 'status': status})
        check = self.artifact({'synthetic': 'independent state comparison, not real human evidence'})
        trial['oracle'] = self.artifact({
            'trial_id': trial['trial_id'], 'execution_sha256': trial['execution']['sha256'],
            'case_sha256': row['content_sha256'], 'rubric_sha256': row['expected_output_or_rubric']['sha256'],
            'independent_label_sha256': row['independent_label']['sha256'],
            'outcome': outcome, 'checker': {'kind': 'deterministic', 'evidence': check},
            'checks': [{'kind': 'final_goal', 'status': outcome, 'evidence': check},
                       {'kind': 'forbidden_effect', 'status': 'pass', 'evidence': check}],
        })

    def request(self):
        return {'candidates': self.candidates, 'trials': self.trials,
                'design': self.design, 'artifacts': self.artifacts}

    def score(self):
        return MODULE.score(**self.request())


def metric(report, arm='A', k=2, name='pass_pow_k'):
    return report['arms'][arm][str(k)][name]


def test_hand_computable_heterogeneity_is_not_power_of_macro_success():
    fixture = Synthetic([(['pass', 'pass'], ['fail', 'pass']), (['fail', 'fail'], ['pass', 'pass'])])
    before = copy.deepcopy(fixture.request())
    report = fixture.score()
    assert report['status'] == 'descriptive'
    assert metric(report, k=1)['value'] == .5
    assert metric(report)['value'] == .5  # not (.5)**2
    assert metric(report, name='pass_at_k')['value'] == .5  # not 1-(1-.5)**2
    assert metric(report, arm='B')['value'] == .5
    assert metric(report, arm='B', name='pass_at_k')['value'] == 1
    assert fixture.request() == before
    assert report['economics']['usage'] is None and report['economics']['cost'] is None
    assert all(a['cost'] is None for a in report['attempts'])
    assert report['source_time_and_predeclaration'] == 'unavailable'
    assert report['external_acceptance'] == 'unknown'
    assert report['population']['estimate'] is None


@pytest.mark.parametrize('n,c,k,at,power', [(3, 1, 2, 2/3, 0), (5, 3, 2, .9, .3), (5, 0, 5, 0, 0), (5, 5, 5, 1, 1), (4, 2, 1, .5, .5)])
def test_combinatorial_math(n, c, k, at, power):
    result = MODULE.pass_metrics(n, c, k)
    assert result['pass_at_k'] == pytest.approx(at)
    assert result['pass_pow_k'] == pytest.approx(power)


@pytest.mark.parametrize('n,c,k', [(0, 0, 1), (2, 3, 1), (2, -1, 1), (2, 1, 0), (2, 1, 3), (True, 1, 1), (2, 1, 1.0), (100000, 1, 1)])
def test_invalid_counts(n, c, k):
    with pytest.raises(ValueError):
        MODULE.pass_metrics(n, c, k)


def test_fixed_k_denominator_excludes_short_case_from_every_metric():
    fixture = Synthetic([(['pass'] * 5, ['fail'] * 5), (['fail'] * 2, ['pass'] * 2)], ks=(1, 2, 5))
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 1
    assert report['cohort']['case_coverage'] == .5
    assert 'insufficient_scheduled_trials_for_all_k' in report['cohort']['excluded'][0]['reasons']
    for k in (1, 2, 5):
        assert metric(report, k=k)['case_count'] == 1
        assert metric(report, k=k)['value'] == 1
        assert metric(report, arm='B', k=k)['value'] == 0
    assert report['cohort']['excluded'][0]['arms']['A']['metrics'] is None


@pytest.mark.parametrize('change', ['missing', 'oracle', 'execution', 'decoding', 'environment', 'command', 'input', 'source_context', 'case_sha256', 'dataset_version', 'group_id', 'root_cause_id', 'protocol', 'seed', 'order', 'unknown_seed'])
def test_one_unknown_or_pin_mismatch_withholds_whole_case(change):
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    trial = fixture.trials[0]
    if change == 'missing':
        fixture.trials.pop(0)
    elif change == 'unknown_seed':
        fixture.design['schedule'][trial['case_id']][0]['seed'] = None
        trial['seed'] = None
        fixture.freeze()
    elif change in ('decoding', 'environment', 'command'):
        trial['pins'] = copy.deepcopy(trial['pins'])
        trial['pins'][change] = None
    else:
        trial[change] = None
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 0
    assert metric(report)['value'] is None
    assert report['runtime_task_reliability']['status'] == 'unavailable'
    assert report['cohort']['excluded']
    if change == 'missing':
        assert len(report['cohort']['missing_attempts']) == 1
    else:
        assert report['cohort']['unavailable_attempts'] >= 1


def test_failures_count_but_dispatch_refusal_is_not_task_failure():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'fail'])])
    report = fixture.score()
    assert metric(report, k=1)['value'] == .5
    assert len(report['attempts']) == 4
    fixture.bind_trial(fixture.trials[0], fixture.candidates[0], 'fail', status='dispatch_refused')
    report = fixture.score()
    assert len(report['attempts']) == 4
    assert report['attempts'][0]['outcome'] is None
    assert metric(report, k=1)['value'] is None
    assert report['historical_review_verdict_consistency']['status'] == 'not_evaluated'


def test_declared_model_and_prompt_treatments_allowed_undeclared_change_rejected():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    assert fixture.score()['status'] == 'descriptive'
    fixture.design['treatment_fields'] = ['prompt']
    fixture.freeze()
    with pytest.raises(ValueError, match='undeclared treatment'):
        fixture.score()


@pytest.mark.parametrize('kind', ['tamper', 'missing', 'fake_boolean'])
def test_manifest_and_attestation_do_not_prove_evidence(kind):
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    manifest = fixture.design['manifest']
    if kind == 'tamper':
        fixture.artifacts[manifest['ref']] = '{}'
    elif kind == 'missing':
        del fixture.artifacts[manifest['ref']]
    else:
        fixture.design['manifest'] = {'ref': 'unverified', 'sha256': 'e' * 64, 'verified': True}
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 0
    assert report['cohort']['design_reasons']
    assert report['evidence_authenticity'] == 'unavailable'


def test_paired_deltas_on_same_cases_and_repeat_orders():
    fixture = Synthetic([(['pass', 'pass'], ['fail', 'pass']), (['fail', 'fail'], ['pass', 'pass'])])
    report = fixture.score()
    pair = report['paired'][0]
    assert pair['case_count'] == 2
    assert pair['metrics']['1']['pass_at_k']['delta'] == .25
    assert pair['metrics']['2']['pass_at_k']['delta'] == .5
    assert pair['metrics']['2']['pass_pow_k']['delta'] == 0
    assert pair['metrics']['1']['pass_at_k']['improved_cases'] == 1
    assert pair['metrics']['1']['pass_at_k']['worsened_cases'] == 1
    assert pair['practical_delta'] == .1
    assert pair['metrics']['1']['pass_at_k']['meets_practical_delta_descriptively'] is True
    assert {t['order'] for t in fixture.trials if t['arm'] == 'A'} == {0, 1}


def test_clusters_close_root_and_group_links_transitively():
    values = [(['pass', 'fail'], ['fail', 'pass'])] * 4
    fixture = Synthetic(values, groups=['g1', 'g1', 'g2', 'g3'], roots=['r1', 'r2', 'r2', 'r3'])
    report = fixture.score()
    assert report['uncertainty']['cluster_count'] == 2
    assert report['uncertainty']['cluster_members'][0] == [f'SYNTHETIC-case-{i}' for i in range(3)]
    assert metric(report)['interval_95'] is None
    assert report['uncertainty']['status'] == 'insufficient_clusters'


def test_k5_two_selected_groups_has_no_zero_uncertainty():
    fixture = Synthetic([(['pass'] * 5, ['pass'] * 5)] * 2, ks=(1, 5))
    report = fixture.score()
    assert metric(report, k=5)['value'] == 1
    assert metric(report, k=5)['interval_95'] is None
    assert report['paired'][0]['metrics']['5']['pass_pow_k']['interval_95'] is None


def test_nondegenerate_cluster_bootstrap_is_deterministic_and_paired():
    fixture = Synthetic([(['fail', 'fail'], ['fail', 'pass']),
                         (['fail', 'pass'], ['pass', 'pass']),
                         (['pass', 'pass'], ['fail', 'fail']),
                         (['fail', 'fail'], ['pass', 'pass'])])
    report = fixture.score()
    assert report['uncertainty']['status'] == 'available'
    assert metric(report, k=1)['interval_95'][0] < metric(report, k=1)['interval_95'][1]
    assert report['paired'][0]['metrics']['1']['pass_at_k']['interval_95'] is not None
    fixture.trials.reverse()
    fixture.candidates.reverse()
    assert fixture.score() == report
    fixture.design['bootstrap']['seed'] = 9
    fixture.freeze()
    assert fixture.score()['uncertainty']['seed'] == 9


def test_degenerate_bootstrap_never_reports_zero_width():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'fail'])] * 4)
    report = fixture.score()
    assert report['uncertainty']['status'] == 'available'
    assert metric(report, k=1)['status'] == 'degenerate_bootstrap'
    assert metric(report, k=1)['interval_95'] is None
    assert report['paired'][0]['metrics']['1']['pass_at_k']['status'] == 'degenerate_bootstrap'


def test_strata_preserved_and_cross_stratum_root_withholds_intervals():
    fixture = Synthetic([(['fail', 'fail'], ['pass', 'pass'])] * 3 + [(['pass', 'pass'], ['fail', 'fail'])] * 3,
                        strata=['s1'] * 3 + ['s2'] * 3)
    report = fixture.score()
    assert report['uncertainty']['strata'] == {'s1': {'clusters': 3, 'cases': 3}, 's2': {'clusters': 3, 'cases': 3}}
    # Stratum allocation is fixed: within-stratum constant values give no variation.
    assert metric(report, k=1)['value'] == .5
    assert metric(report, k=1)['interval_95'] is None
    other = Synthetic([(['pass', 'fail'], ['pass', 'pass'])] * 4,
                      roots=['shared', 'shared', 'r2', 'r3'], strata=['s1', 's2', 's1', 's2'])
    report = other.score()
    assert report['uncertainty']['status'] == 'cross_stratum_cluster'
    assert metric(report)['interval_95'] is None


def test_judge_boolean_and_review_verdict_are_not_independent_outcomes():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    trial = fixture.trials[0]
    oracle = json.loads(fixture.artifacts[trial['oracle']['ref']])
    oracle['checker'] = {'kind': 'llm_judge', 'validated': True, 'role': 'expert', 'attestation_ref': 'blind'}
    trial['oracle'] = fixture.artifact(oracle)
    report = fixture.score()
    assert 'independent_checker_unavailable' in report['attempts'][0]['reasons']
    assert metric(report)['value'] is None


def test_unknown_goal_and_oracle_conflicts_never_become_failure():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    trial = fixture.trials[0]
    oracle = json.loads(fixture.artifacts[trial['oracle']['ref']])
    oracle['checks'][0]['status'] = 'unknown'
    trial['oracle'] = fixture.artifact(oracle)
    report = fixture.score()
    assert report['attempts'][0]['outcome'] is None
    assert metric(report)['value'] is None
    oracle['checks'][0]['status'] = 'fail'
    trial['oracle'] = fixture.artifact(oracle)
    report = fixture.score()
    assert 'outcome_unknown_or_conflicting' in report['attempts'][0]['reasons']


def test_current_quarantined_candidates_are_not_trials_or_gold():
    path = ROOT / 'benchmarks/experiments/evalops/dataset-v1/artifacts/candidates.jsonl'
    candidates = [json.loads(line) for line in path.read_text().splitlines() if line]
    report = MODULE.score(candidates)
    assert len(candidates) == 240
    assert report['status'] == 'needs_labels'
    assert report['candidate_coverage'] == {'records': 240, 'needs_labels': 240, 'unavailable': 240}
    assert report['runtime_task_reliability']['status'] == 'unavailable'
    assert report['arms'] == {} and report['attempts'] == []
    assert report['economics']['usage'] is None


@pytest.mark.parametrize('corrupt', ['duplicate', 'outside', 'extra_attempt', 'weighted_wilson', 'bad_k', 'huge_work'])
def test_ambiguous_or_unbounded_design_rejected(corrupt):
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    if corrupt == 'duplicate':
        fixture.trials.append(copy.deepcopy(fixture.trials[0]))
    elif corrupt == 'outside':
        fixture.trials[0]['case_id'] = 'foreign'
    elif corrupt == 'extra_attempt':
        fixture.trials[0]['repeat_id'] = 'undeclared-retry'
    elif corrupt == 'weighted_wilson':
        fixture.design['bootstrap']['method'] = 'weighted_wilson'
    elif corrupt == 'bad_k':
        fixture.design['ks'] = [0]
    else:
        fixture.design['bootstrap']['resamples'] = 1000000
    fixture.freeze()
    with pytest.raises(ValueError):
        fixture.score()


def invoke(path, *args):
    return subprocess.run([sys.executable, '-m', 'benchmarks.tools.evalops.score_reliability',
                           '--input', str(path), *args], cwd=ROOT, capture_output=True, text=True, check=False)


def test_cli_json_export_and_input_alias_protection(tmp_path):
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    path = tmp_path / 'synthetic-request.json'
    path.write_text(json.dumps(fixture.request()))
    result = invoke(path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == fixture.score()
    output = tmp_path / 'report.json'
    result = invoke(path, '--output', str(output))
    assert result.returncode == 0
    assert json.loads(output.read_text()) == fixture.score()
    for mode in ('same', 'symlink', 'hardlink'):
        alias = path if mode == 'same' else tmp_path / mode
        if mode == 'symlink':
            alias.symlink_to(path)
        elif mode == 'hardlink':
            alias.hardlink_to(path)
        result = invoke(path, '--output', str(alias))
        assert result.returncode == 2
        assert json.loads(result.stderr)['status'] == 'error'
        assert json.loads(path.read_text()) == fixture.request()


@pytest.mark.parametrize('text', ['{"candidates":[],"candidates":[]}', '{"candidates":[],"x":NaN}',
                                  '{"candidates":[],"x":1e9999}', '{"candidates":[],"x":1}',
                                  '[' * 100 + '0' + ']' * 100, 'not-json'])
def test_cli_strict_json_errors(tmp_path, text):
    path = tmp_path / 'bad.json'
    path.write_text(text)
    result = invoke(path)
    assert result.returncode == 2
    assert result.stdout == ''
    assert json.loads(result.stderr)['status'] == 'error'


def test_api_depth_and_byte_bounds():
    nested = None
    for _ in range(42):
        nested = [nested]
    with pytest.raises(ValueError, match='structure limit'):
        MODULE.score([], artifacts={'synthetic': nested})
    with pytest.raises(ValueError, match='byte limit'):
        MODULE.score([], artifacts={'synthetic': 'x' * MODULE.MAX_BYTES})


def test_missing_bridge_withholds_entire_linked_component():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])] * 4,
                        groups=['g1', 'g1', 'g2', 'g3'], roots=['r1', 'r2', 'r2', 'r3'])
    fixture.trials = [t for t in fixture.trials if not (t['case_id'] == 'SYNTHETIC-case-1' and t['arm'] == 'B' and t['repeat_id'] == 'repeat-0')]
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 1
    assert report['cohort']['per_case'][0]['case_id'] == 'SYNTHETIC-case-3'
    exclusions = {r['case_id']: r['reasons'] for r in report['cohort']['excluded']}
    assert exclusions['SYNTHETIC-case-0'] == ['linked_case_unavailable']
    assert exclusions['SYNTHETIC-case-2'] == ['linked_case_unavailable']
    assert report['status'] == 'partial_descriptive'


# EVALOPS3-EVALUATION-R2-02 topology: cases 0-1 share group g1, cases 1-2 share
# root r2, and cases 3/4/5 have no shared identity. Task ids are all distinct.
BRIDGE_OUTCOMES = [(['pass', 'fail'], ['pass', 'pass']), (['pass', 'pass'], ['fail', 'fail']),
                   (['fail', 'fail'], ['fail', 'pass']), (['pass', 'pass'], ['fail', 'pass']),
                   (['fail', 'pass'], ['pass', 'pass']), (['fail', 'fail'], ['pass', 'fail'])]
ABSENT = object()


def case(i):
    return f'SYNTHETIC-case-{i}'


def bridge_fixture():
    return Synthetic(BRIDGE_OUTCOMES, groups=['g1', 'g1', 'g2', 'g3', 'g4', 'g5'],
                     roots=['r1', 'r2', 'r2', 'r3', 'r4', 'r5'])


def regroup(fixture, index, **changes):
    """Edit one declared grouping, rehash its case and rebind its trials with unchanged outcomes."""
    row = fixture.candidates[index]
    for field, value in changes.items():
        if value is ABSENT:
            row['grouping'].pop(field)
        else:
            row['grouping'][field] = value
    fixture.rehash(row)
    for trial in fixture.trials:
        if trial['case_id'] == row['candidate_id']:
            outcome = json.loads(fixture.artifacts[trial['oracle']['ref']])['outcome']
            trial['case_sha256'] = row['content_sha256']
            trial['group_id'] = row['grouping'].get('group_id')
            trial['root_cause_id'] = row['grouping'].get('root_cause_id')
            fixture.bind_trial(trial, row, outcome)


def test_partial_identity_case_keeps_known_bridges_and_withholds_component():
    control = bridge_fixture().score()
    assert control['cohort']['excluded'] == []
    assert control['uncertainty']['cluster_members'] == [[case(0), case(1), case(2)], [case(3)], [case(4)], [case(5)]]
    assert control['uncertainty']['status'] == 'available'
    fixture = bridge_fixture()
    regroup(fixture, 1, canonical_task_id=None)  # supplied g1/r2 links and evidence remain
    report = fixture.score()
    cohort = report['cohort']
    assert {r['case_id']: r['reasons'] for r in cohort['excluded']} == {
        case(0): ['linked_case_unavailable'], case(1): ['grouping_unavailable'], case(2): ['linked_case_unavailable']}
    assert [r['case_id'] for r in cohort['per_case']] == [case(3), case(4), case(5)]
    assert (cohort['declared_cases'], cohort['eligible_cases'], cohort['case_coverage']) == (6, 3, .5)
    # Held cases keep every planned attempt and their counts; only metrics are withheld.
    assert (cohort['expected_attempts'], cohort['supplied_attempts'], cohort['unavailable_attempts']) == (24, 24, 0)
    assert cohort['missing_attempts'] == [] and len(report['attempts']) == 24
    held = {r['case_id']: r['arms'] for r in cohort['excluded']}
    assert held[case(0)]['B'] == {'n': 2, 'observed_attempts': 2, 'successes': 2, 'failures': 0, 'metrics': None}
    # Three singletons remain, below the four-cluster minimum (was five, interval [.1, .7]).
    assert report['uncertainty']['cluster_members'] == [[case(3)], [case(4)], [case(5)]]
    assert report['uncertainty']['status'] == 'insufficient_clusters'
    for arm in ('A', 'B'):
        for k in (1, 2):
            for name in ('pass_at_k', 'pass_pow_k'):
                assert metric(report, arm, k, name)['case_count'] == 3
                assert metric(report, arm, k, name)['interval_95'] is None
    # Hand-computed on cases 3/4/5 (was .4 for arm A, k=1 on five cases).
    assert metric(report, k=1, name='pass_at_k')['value'] == .5
    assert metric(report, k=2, name='pass_at_k')['value'] == pytest.approx(2 / 3)
    assert metric(report, k=2)['value'] == pytest.approx(1 / 3)
    assert metric(report, arm='B', k=1)['value'] == pytest.approx(2 / 3)
    pair = report['paired'][0]
    assert pair['case_count'] == 3
    assert pair['metrics']['1']['pass_at_k']['delta'] == pytest.approx(1 / 6)
    assert pair['metrics']['1']['pass_at_k']['interval_95'] is None
    assert report['status'] == 'partial_descriptive'


@pytest.mark.parametrize('field,held,status,value', [
    ('canonical_task_id', {0, 2}, 'insufficient_clusters', .5),  # g1 and r2 remain
    ('group_id', {2}, 'available', .5),                          # only r2 remains
    ('root_cause_id', {0}, 'available', .375),                   # only g1 remains
])
def test_each_missing_identity_type_withholds_only_remaining_known_bridges(field, held, status, value):
    fixture = bridge_fixture()
    regroup(fixture, 1, **{field: None})
    report = fixture.score()
    exclusions = {r['case_id']: r['reasons'] for r in report['cohort']['excluded']}
    assert 'grouping_unavailable' in exclusions.pop(case(1))
    assert exclusions == {case(i): ['linked_case_unavailable'] for i in held}
    eligible = [case(i) for i in (0, 2, 3, 4, 5) if i not in held]
    assert [r['case_id'] for r in report['cohort']['per_case']] == eligible
    assert report['uncertainty']['cluster_members'] == [[c] for c in eligible]
    assert report['uncertainty']['status'] == status
    assert metric(report, k=1)['case_count'] == len(eligible)
    assert metric(report, k=1)['value'] == value


def test_incomplete_cases_propagate_holds_through_transitive_known_links():
    # 0 -g1- 1(task absent) -r2- 2 -g2- 3; 4(only task-5 known) -task- 5; 6/7 unlinked.
    fixture = Synthetic([(['pass', 'fail'], ['fail', 'pass'])] * 8,
                        groups=['g1', 'g1', 'g2', 'g2', 'g4', 'g5', 'g6', 'g7'],
                        roots=['r1', 'r2', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7'])
    regroup(fixture, 1, canonical_task_id=None)
    regroup(fixture, 4, group_id=None, root_cause_id=None, canonical_task_id='task-5')
    report = fixture.score()
    exclusions = {r['case_id']: r['reasons'] for r in report['cohort']['excluded']}
    assert exclusions == {
        case(0): ['linked_case_unavailable'], case(1): ['grouping_unavailable'],
        case(2): ['linked_case_unavailable'], case(3): ['linked_case_unavailable'],
        case(4): ['grouping_unavailable', 'unavailable_attempt'], case(5): ['linked_case_unavailable']}
    assert [r['case_id'] for r in report['cohort']['per_case']] == [case(6), case(7)]
    assert report['uncertainty']['status'] == 'insufficient_clusters'
    assert metric(report, k=1)['interval_95'] is None


@pytest.mark.parametrize('invalid', [None, '', '   ', ABSENT, 7, ['task-1']])
def test_invalid_identity_adds_no_edge_and_equal_text_across_types_never_links(invalid):
    fixture = bridge_fixture()
    regroup(fixture, 1, canonical_task_id=invalid)
    # Same strings as case 1's surviving g1/r2, but under other identity types.
    regroup(fixture, 4, root_cause_id='g1', canonical_task_id='r2')
    report = fixture.score()
    assert {r['case_id']: r['reasons'] for r in report['cohort']['excluded']} == {
        case(0): ['linked_case_unavailable'], case(1): ['grouping_unavailable'], case(2): ['linked_case_unavailable']}
    assert report['uncertainty']['cluster_members'] == [[case(3)], [case(4)], [case(5)]]


def test_closure_never_links_absent_null_or_cross_type_identities():
    # Every invalid identity sits on a case already held for grouping_unavailable,
    # so scorer output cannot show a null union; check the closure contract directly.
    rows = [{'case_id': 'a', 'group_id': 'x', 'root_cause_id': None, 'canonical_task_id': ''},
            {'case_id': 'b', 'group_id': None, 'root_cause_id': 'x', 'canonical_task_id': '  '},
            {'case_id': 'c', 'group_id': None, 'root_cause_id': None, 'canonical_task_id': 'x'},
            {'case_id': 'd', 'group_id': 'x', 'root_cause_id': '', 'canonical_task_id': None}]
    assert [[r['case_id'] for r in g] for g in MODULE._clusters(rows)] == [['a', 'd'], ['b'], ['c']]
    malformed = [{'case_id': 'e', 'group_id': ['x']}, {'case_id': 'f', 'root_cause_id': 7},
                 {'case_id': 'g', 'root_cause_id': 7}, {'case_id': 'h'}]
    assert [[r['case_id'] for r in g] for g in MODULE._clusters(malformed)] == [['e'], ['f'], ['g'], ['h']]


def test_explicit_group_and_stratum_comparisons_are_case_macro():
    fixture = Synthetic([(['fail', 'fail'], ['pass', 'pass']),
                         (['pass', 'pass'], ['pass', 'fail']),
                         (['fail', 'fail'], ['fail', 'fail'])],
                        groups=['g1', 'g1', 'g2'], strata=['s1', 's1', 's2'])
    report = fixture.score()
    assert report['grouped'][0]['case_count'] == 2
    assert report['grouped'][0]['arms']['A']['1']['pass_at_k'] == .5
    assert report['strata']['s1']['paired'][0]['metrics']['1']['pass_at_k'] == .25
    assert report['strata']['s2']['arms']['A']['1']['pass_at_k'] == 0
    assert report['strata']['s2']['paired'][0]['metrics']['2']['pass_pow_k'] == 0


def test_partial_cohort_denominator_does_not_vary_with_k_or_arm():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass']), (['fail', 'fail'], ['fail', 'fail'])])
    fixture.trials[0]['oracle'] = None
    report = fixture.score()
    assert report['status'] == 'partial_descriptive'
    assert report['cohort']['eligible_cases'] == 1
    for arm in ('A', 'B'):
        for k in (1, 2):
            assert metric(report, arm=arm, k=k)['case_count'] == 1
            assert metric(report, arm=arm, k=k)['value'] == 0
    assert report['paired'][0]['case_count'] == 1
    assert report['cohort']['supplied_attempts'] == 8
    assert len(report['attempts']) == 8


def test_source_manifest_must_bind_case_source():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    for arm in fixture.design['arms'].values():
        arm['pins'] = copy.deepcopy(arm['pins'])
        arm['pins']['source'] = fixture.artifact({'sources': []})
    # Equal source pin across arms; declare protocols with that shared source.
    fixture.design['arms']['B']['pins']['source'] = fixture.design['arms']['A']['pins']['source']
    for arm in fixture.design['arms'].values():
        arm['protocol'] = fixture.artifact(arm['pins'])
    fixture.freeze()
    for trial in fixture.trials:
        arm = fixture.design['arms'][trial['arm']]
        trial['protocol'], trial['pins'] = arm['protocol'], arm['pins']
        fixture.bind_trial(trial, fixture.candidates[0], 'pass')
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 0
    assert 'source_manifest_mismatch' in report['attempts'][0]['reasons']


def test_boolean_seed_is_not_integer_pin_match():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    trial = fixture.trials[0]
    fixture.design['schedule'][trial['case_id']][0]['seed'] = 1
    fixture.freeze()
    trial['seed'] = True
    fixture.bind_trial(trial, fixture.candidates[0], 'pass')
    report = fixture.score()
    assert 'seed_mismatch_or_unknown' in report['attempts'][0]['reasons']


def test_design_missing_protocol_pin_and_current_release_cannot_be_admitted():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    row = fixture.candidates[0]
    row['dataset_version'] = '1.0.0'
    fixture.rehash(row)
    for trial in fixture.trials:
        trial['dataset_version'], trial['case_sha256'] = row['dataset_version'], row['content_sha256']
        fixture.bind_trial(trial, row, 'pass')
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 0
    assert 'candidate_release_cannot_admit' in report['cohort']['excluded'][0]['reasons']
    for arm in fixture.design['arms'].values():
        arm['pins']['decoding'] = None
        arm['protocol'] = fixture.artifact(arm['pins'])
    fixture.freeze()
    report = fixture.score()
    assert report['cohort']['design_reasons']


def test_paired_bootstrap_keeps_perfectly_correlated_arms_together():
    fixture = Synthetic([(['pass', 'pass'], ['pass', 'pass']),
                         (['fail', 'fail'], ['fail', 'fail']),
                         (['pass', 'fail'], ['pass', 'fail']),
                         (['fail', 'pass'], ['fail', 'pass'])])
    report = fixture.score()
    assert metric(report, k=1)['interval_95'] is not None
    # Independent arm resampling would invent variation in this exact zero delta.
    for k in (1, 2):
        for m in ('pass_at_k', 'pass_pow_k'):
            pair = report['paired'][0]['metrics'][str(k)][m]
            assert pair['delta'] == 0
            assert pair['interval_95'] is None
            assert pair['status'] == 'degenerate_bootstrap'


@pytest.mark.parametrize('field', ['protocol_sha256', 'input_lock_sha256', 'source_row', 'source_snapshot'])
def test_source_and_dataset_hashes_need_matching_supplied_bytes(field):
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    row = fixture.candidates[0]
    if field in ('protocol_sha256', 'input_lock_sha256'):
        row[field] = 'e' * 64
    elif field == 'source_row':
        row['source']['row_sha256'] = 'e' * 64
    else:
        del fixture.artifacts[row['source']['snapshot']]
    fixture.rehash(row)
    report = fixture.score()
    assert report['cohort']['eligible_cases'] == 0
    assert report['cohort']['excluded'][0]['reasons']
    assert metric(report)['value'] is None


def test_dispatch_counts_and_nullable_usage_do_not_imply_task_outcomes():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    fixture.bind_trial(fixture.trials[0], fixture.candidates[0], 'pass', status='dispatch_refused')
    report = fixture.score()
    assert report['dispatch_infrastructure']['counts']['dispatch_refused'] == 1
    assert report['dispatch_infrastructure']['counts']['executed'] == 3
    assert report['attempts'][0]['execution_status'] == 'dispatch_refused'
    assert report['attempts'][0]['usage'] is None
    assert metric(report)['value'] is None


def test_malformed_nested_evidence_cannot_escape_as_task_success():
    fixture = Synthetic([(['pass', 'fail'], ['pass', 'pass'])])
    trial = fixture.trials[0]
    oracle = json.loads(fixture.artifacts[trial['oracle']['ref']])
    oracle['checks'][0]['kind'] = ['not', 'a', 'kind']
    trial['oracle'] = fixture.artifact(oracle)
    assert fixture.score()['cohort']['eligible_cases'] == 0


def test_large_integer_api_input_has_structured_validation_error():
    with pytest.raises(ValueError, match='bounded finite'):
        MODULE.score([], artifacts={'test': 10**1000})
