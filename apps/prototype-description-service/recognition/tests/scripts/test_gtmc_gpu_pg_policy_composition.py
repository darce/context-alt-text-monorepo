"""Offline command-specific policy composition regressions (C82R-G4ADJ-F1)."""
import pytest

from recognition.tests.scripts.test_gtmc_gpu_pg_findings import (
    COL, FakeCluster, FakeSession, NATIVE_TENANT_QUAL, PRIMARY, TENANT_A, TENANT_B,
    _policy, _policy_issue_fields, _run, _facts, _missing_codes, _deny_actual_connect,
)

TABLE = 'describe_operations'


def _guard(cluster, command='ALL', qual=NATIVE_TENANT_QUAL, roles=('public',)):
    policy = _policy('tenant_guard', qual, roles, command)
    policy['permissive'] = 'RESTRICTIVE'
    cluster.policies[TABLE].append(policy)
    return policy


def _unsafe(result):
    return [i for i in result['section']['contradictions']
            if i['code'] == 'unsafe_policy_predicate' and i['field'].startswith(f'catalog.rls.{TABLE}.')]


def test_c82_d2_all_policy_without_with_check_inherits_using():
    cluster = FakeCluster()
    cluster.policies[TABLE][0]['with_check'] = None
    assert not _policy_issue_fields(_run(cluster), TABLE)


def test_c82_d2_restrictive_true_is_neutral():
    cluster = FakeCluster()
    _guard(cluster, qual='true')
    assert not _policy_issue_fields(_run(cluster), TABLE)


@pytest.mark.parametrize('command', ['ALL', 'SELECT', 'INSERT', 'UPDATE', 'DELETE'])
def test_c82_d2_restrictive_tenant_guard_bounds_permissive_union(command):
    cluster = FakeCluster()
    extra = _policy('allow_all', 'true', cmd=command)
    cluster.policies[TABLE].append(extra)
    _guard(cluster)
    result = _run(cluster)
    assert not _policy_issue_fields(result, TABLE)
    assert _facts(result)[f'pg:visibility:{PRIMARY}:media-101']['foreign_demand_rows'] == 0


@pytest.mark.parametrize('command', ['ALL', 'INSERT', 'UPDATE', 'DELETE'])
def test_c82_d2_select_guard_does_not_bound_other_commands(command):
    cluster = FakeCluster()
    cluster.policies[TABLE].append(_policy('allow_all', 'true', cmd=command))
    _guard(cluster, command='SELECT')
    result = _run(cluster)
    assert _unsafe(result)
    if command == 'ALL':
        assert any(i['field'].endswith('.with_check') for i in _unsafe(result))
        assert not any(i['field'].endswith('.qual') for i in _unsafe(result) if 'SELECT' in i['detail'])


def test_c82_d2_literal_true_check_is_not_inherited():
    cluster = FakeCluster()
    cluster.policies[TABLE][0]['with_check'] = 'true'
    assert any(i['field'].endswith('.with_check') for i in _unsafe(_run(cluster)))


@pytest.mark.parametrize('dimension', ['predicate', 'permissiveness', 'roles', 'command'])
def test_c82_d2_unknown_guard_semantics_stay_missing(dimension):
    cluster = FakeCluster()
    guard = _guard(cluster)
    if dimension == 'predicate':
        guard['qual'] = guard['with_check'] = 'tenant_id IS NOT NULL'
    elif dimension == 'permissiveness':
        guard['permissive'] = 'UNKNOWN'
    elif dimension == 'roles':
        guard['roles'] = ['unobserved_group']
    else:
        guard['cmd'] = 'UNKNOWN'
    assert _policy_issue_fields(_run(cluster), TABLE)


@pytest.mark.parametrize('usage', [True, False])
def test_c82_d2_fake_uses_restrictive_and_observed_role_usage(usage):
    cluster = FakeCluster()
    cluster.role_usage['reader_group'] = usage
    cluster.policies[TABLE][0]['qual'] = 'true'
    _guard(cluster, roles=('reader_group',))
    session = FakeSession(cluster, PRIMARY)
    session.tenant = TENANT_A
    assert session._allowed(TABLE, TENANT_A)
    assert session._allowed(TABLE, TENANT_B) is (not usage)


def test_c82_d2_restrictive_only_has_no_permissive_grant():
    cluster = FakeCluster()
    cluster.policies[TABLE] = []
    _guard(cluster)
    session = FakeSession(cluster, PRIMARY)
    session.tenant = TENANT_A
    assert not session._allowed(TABLE, TENANT_A)


@pytest.mark.parametrize('value', [None, '', 'unknown', True])
def test_c82_d2_missing_predicate_is_not_a_known_true(value):
    cluster = FakeCluster()
    cluster.policies[TABLE][0]['qual'] = value
    cluster.policies[TABLE][0]['with_check'] = value
    result = _run(cluster)
    assert 'policy_semantics_unrecognised' in _missing_codes(result)
    assert not _unsafe(result)


@pytest.mark.parametrize('read_guard', [True, False])
def test_c82_d2_using_and_check_are_independent(read_guard):
    cluster = FakeCluster()
    cluster.policies[TABLE][0].update(qual='true', with_check='true')
    guard = _guard(cluster, qual=NATIVE_TENANT_QUAL if read_guard else 'true')
    guard['with_check'] = 'true' if read_guard else NATIVE_TENANT_QUAL
    issues = _unsafe(_run(cluster))
    assert issues
    assert {i['field'].rsplit('.', 1)[1] for i in issues} == ({'with_check'} if read_guard else {'qual'})


@pytest.mark.parametrize('usage', [True, False])
def test_c82_d2_restrictive_group_applicability(usage):
    cluster = FakeCluster()
    cluster.role_usage['reader_group'] = usage
    cluster.policies[TABLE][0].update(qual='true', with_check='true')
    _guard(cluster, roles=('reader_group',))
    assert bool(_unsafe(_run(cluster))) is (not usage)


def test_c82_d2_insert_uses_check_without_using():
    cluster = FakeCluster()
    policy = _policy('insert_scope', 'unknown', cmd='INSERT')
    policy['with_check'] = NATIVE_TENANT_QUAL
    cluster.policies[TABLE].append(policy)
    assert not _policy_issue_fields(_run(cluster), TABLE)


@pytest.mark.parametrize('command', ['INSERT', 'UPDATE'])
def test_c82_d2_non_all_null_check_stays_missing(command):
    cluster = FakeCluster()
    policy = _policy('write_scope', NATIVE_TENANT_QUAL, cmd=command)
    policy['with_check'] = None
    cluster.policies[TABLE].append(policy)
    result = _run(cluster)
    assert 'policy_semantics_unrecognised' in _missing_codes(result)
    assert not _unsafe(result)
