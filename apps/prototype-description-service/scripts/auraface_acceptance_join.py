"""Pure captured-record joins for Face G3; this is not an acceptance validator.

Transport versions are independent of the unchanged snapshot V1. Supported
nested records are closed: extensions need explicit producer/collector review.
A successful identity join still returns no snapshot/sidecar while the existing
validator's repair ABI and the branch helper bytes are unavailable.

No expected value is ever copied into an observed field. The ledger reports
only indices, digests and fixed codes, never input text, identifiers or errors.
PROV-01 / EMB-01 / EMB-05 / WEB-16:
https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#prov-01
https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#emb-01
https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/ml-systems.md#emb-05
https://github.com/darce/heuristics-canon/blob/v0.25.6/lexicons/security.md#web-16
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math

MAX_RECORDS = 128
MAX_NODES = 50000
MAX_DEPTH = 24
MAX_ITEMS = 512
MAX_TEXT = 512
RAW_NORM_ABS_TOLERANCE = 1e-5


def _raw_norm_span_exceeds_tolerance(values):
    """Compare exact int/float ratios without rounding integers to binary64."""
    low_num, low_den = min(values).as_integer_ratio()
    high_num, high_den = max(values).as_integer_ratio()
    tolerance_num, tolerance_den = RAW_NORM_ABS_TOLERANCE.as_integer_ratio()
    return ((high_num * low_den - low_num * high_den) * tolerance_den
            > tolerance_num * high_den * low_den)


class RecordError(ValueError):
    """Exception contents are restricted to fixed public reason codes."""


def _fail(code):
    raise RecordError(code)


def _closed(value, fields, versions=()):
    if not isinstance(value, dict):
        _fail('malformed')
    # Missing/bool/unknown versions take precedence over shape errors.
    for key in versions:
        if type(value.get(key)) is not int or value[key] != 1:
            _fail('incompatible_version')
    keys = set(fields.split())
    if set(value) - keys:
        _fail('malformed')
    if keys - set(value):
        _fail('incomplete')
    return value


def _text(value):
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT:
        _fail('incomplete' if value is None else 'malformed')
    # Free text is not a transport for secrets, DSNs or contact addresses.
    if '@' in value or '://' in value or any(ord(c) < 32 for c in value):
        _fail('malformed')
    return value


def _hex(value, width=64):
    _text(value)
    if len(value) != width or any(c not in '0123456789abcdef' for c in value):
        _fail('malformed')
    return value


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum or value.bit_length() > 63:
        _fail('malformed')
    return value


def _number(value, positive=False):
    if type(value) not in (int, float) or (type(value) is int and value.bit_length() > 63) or not math.isfinite(value):
        _fail('malformed')
    if positive and value <= 0:
        _fail('incomplete')
    return value


def _boolean(value):
    if type(value) is not bool:
        _fail('malformed')


def _time(value):
    _text(value)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _fail('malformed')
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail('malformed')
    return parsed


def _fresh(value, now, policy):
    age = (now - _time(value)).total_seconds()
    if age > policy['max_age_seconds']:
        _fail('stale')
    if age < -policy['future_skew_seconds']:
        _fail('future_clock')


def _list(value, nonempty=False):
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        _fail('malformed')
    if nonempty and not value:
        _fail('incomplete')
    return value


def _bounded_json(value):
    """Reject non-JSON objects, cycles, unbounded structures and nonfinite data."""
    todo = [(value, 0)]
    count = 0
    while todo:
        node, depth = todo.pop()
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            _fail('oversized')
        if isinstance(node, dict):
            if len(node) > MAX_ITEMS or any(not isinstance(k, str) for k in node):
                _fail('malformed')
            for key in node:
                _text(key)
            todo.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            _list(node)
            todo.extend((child, depth + 1) for child in node)
        elif isinstance(node, str):
            _text(node)
        elif node is None or type(node) is bool:
            pass
        elif type(node) in (int, float):
            _number(node)
        else:
            _fail('malformed')


def record_digest(value):
    _bounded_json(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _source(value):
    if value is None:
        _fail('incomplete')
    _closed(value, 'source_identity_version source_git_sha source_tree build_context_manifest_sha256 service_lock_sha256 image_variant build_time identity_document_sha256', ('source_identity_version',))
    for key in ('source_git_sha', 'source_tree'):
        _hex(value[key], 40)
    for key in ('build_context_manifest_sha256', 'service_lock_sha256', 'identity_document_sha256'):
        _hex(value[key])
    _text(value['image_variant'])
    _time(value['build_time'])


def _status(value):
    if value['collection_status'] not in ('complete', 'incomplete', 'failed', 'not_applicable'):
        _fail('malformed')
    if value['reason_code'] is not None:
        _text(value['reason_code'])
    if value['collection_status'] != 'complete':
        _fail('failed' if value['collection_status'] == 'failed' else 'incomplete')
    if value['reason_code'] is not None:
        _fail('incomplete')


def _image(value, source, isolation):
    _closed(value, 'role process_instance_id container_id registry_manifest_digest digest_type platform image_config_digest identity_document_sha256 source_identity resource_policy_id')
    for key in ('role', 'process_instance_id', 'container_id', 'resource_policy_id', 'platform'):
        _text(value[key])
    for key in ('registry_manifest_digest', 'image_config_digest'):
        digest = value[key]
        if not isinstance(digest, str) or not digest.startswith('sha256:'):
            _fail('malformed')
        _hex(digest[7:])
    _hex(value['identity_document_sha256'])
    _source(value['source_identity'])
    if value['source_identity'] != source or value['identity_document_sha256'] != source['identity_document_sha256']:
        _fail('contradictory_binding')
    if value['resource_policy_id'] != isolation['resource_policy_id']:
        _fail('contradictory_binding')
    if value['digest_type'] not in ('manifest', 'index'):
        _fail('malformed')


def _canonical_tensor_contract(shape, dtype, *, allow_symbolic=False):
    """Normalize ORT's float dtype; only metadata may contain symbolic dims."""
    dtype = _text(dtype)
    dimensions = []
    for size in _list(shape, True):
        dimensions.append(_text(size) if allow_symbolic and isinstance(size, str)
                          else _integer(size, 1))
    return dict(shape=dimensions, dtype='float32' if dtype == 'tensor(float)' else dtype)


def _metadata(value):
    for item in _list(value, True):
        _closed(item, 'name shape dtype')
        _text(item['name'])
        _canonical_tensor_contract(item['shape'], item['dtype'], allow_symbolic=True)


def _session(value, generation, logical_name, now, policy):
    _closed(value, 'session_id runtime_generation_id logical_model_name constructed_at observed_weight_sha256 observed_weight_size_bytes observed_license_sha256 observed_license_size_bytes manifest_expectation_sha256 frozen_preprocessing_sha256 numeric_runtime_fingerprint actual_providers actual_input_metadata actual_output_metadata actual_session_options graph_analysis')
    _text(value['session_id'])
    if value['runtime_generation_id'] != generation or value['logical_model_name'] != logical_name:
        _fail('contradictory_binding')
    constructed = _time(value['constructed_at'])
    if (constructed - now).total_seconds() > policy['future_skew_seconds']:
        _fail('future_clock')
    for key in ('observed_weight_sha256', 'observed_license_sha256', 'manifest_expectation_sha256', 'frozen_preprocessing_sha256', 'numeric_runtime_fingerprint'):
        _hex(value[key])
    _integer(value['observed_weight_size_bytes'], 1); _integer(value['observed_license_size_bytes'], 1)
    for provider in _list(value['actual_providers'], True):
        _text(provider)
    _metadata(value['actual_input_metadata']); _metadata(value['actual_output_metadata'])
    opts = value['actual_session_options']
    _closed(opts, 'intra_op_num_threads inter_op_num_threads execution_mode graph_optimization_level')
    _integer(opts['intra_op_num_threads'], 1); _integer(opts['inter_op_num_threads'], 1)
    _text(opts['execution_mode']); _text(opts['graph_optimization_level'])
    graph = value['graph_analysis']
    if graph is None:
        _fail('incomplete')
    _closed(graph, 'model_sha256 analysis_sha256 output_l2_normalized')
    _hex(graph['model_sha256']); _hex(graph['analysis_sha256']); _boolean(graph['output_l2_normalized'])
    if graph['model_sha256'] != value['observed_weight_sha256']:
        _fail('contradictory_binding')


def _tensor(value, embedder=False):
    fields = 'sha256 shape dtype contiguous ' + ('channel_samples mean scale' if embedder else 'padding_geometry')
    _closed(value, fields)
    _hex(value['sha256']); _text(value['dtype']); _boolean(value['contiguous'])
    contract = _canonical_tensor_contract(value['shape'], value['dtype'])
    if not value['contiguous'] or contract['dtype'] != 'float32':
        _fail('incomplete')
    if embedder:
        for sample in _list(value['channel_samples'], True):
            _number(sample)
        _number(value['mean']); _number(value['scale'], True)
    else:
        for pad in _list(value['padding_geometry'], True):
            _integer(pad)


def _execution(value, runtime, now, policy):
    if value is None:
        _fail('incomplete')
    _closed(value, 'execution_id runtime_generation_id detector_session_id embedder_session_id captured_at input_lineage detector_input detections_sha256 alignment embedder_input raw_output normalized_output graph_analysis_sha256 completion')
    _text(value['execution_id']); _fresh(value['captured_at'], now, policy)
    sessions = runtime['sessions']
    if value['runtime_generation_id'] != runtime['runtime_generation_id'] or value['detector_session_id'] != sessions['yunet']['session_id'] or value['embedder_session_id'] != sessions['auraface']['session_id']:
        _fail('contradictory_binding')
    if value['completion'] != 'complete':
        _fail('incomplete')
    lineage = value['input_lineage']
    _closed(lineage, 'fixture_id fixture_sha256 independent_reference_sha256')
    _text(lineage['fixture_id']); _hex(lineage['fixture_sha256']); _hex(lineage['independent_reference_sha256'])
    _tensor(value['detector_input']); _tensor(value['embedder_input'], True)
    for tensor_key, session_key in (('detector_input', 'yunet'), ('embedder_input', 'auraface')):
        tensor = value[tensor_key]
        metadata = sessions[session_key]['actual_input_metadata']
        if len(metadata) != 1:
            _fail('contradictory_binding')
        actual = _canonical_tensor_contract(tensor['shape'], tensor['dtype'])
        declared = _canonical_tensor_contract(metadata[0]['shape'], metadata[0]['dtype'], allow_symbolic=True)
        if (actual['dtype'] != declared['dtype'] or len(actual['shape']) != len(declared['shape'])
                or any(not isinstance(expected, str) and observed != expected
                       for observed, expected in zip(actual['shape'], declared['shape']))):
            _fail('contradictory_binding')
    _hex(value['detections_sha256'])
    alignment = value['alignment']
    _closed(alignment, 'landmarks_sha256 executing_spec_sha256 template_sha256 affine_sha256 crop_sha256')
    for digest in alignment.values():
        _hex(digest)
    if alignment['executing_spec_sha256'] != sessions['auraface']['frozen_preprocessing_sha256']:
        _fail('contradictory_binding')
    for key in ('raw_output', 'normalized_output'):
        output = value[key]
        _closed(output, 'sha256 dimension norm')
        _hex(output['sha256']); _integer(output['dimension'], 1); _number(output['norm'], True)
        if output['dimension'] != 512:
            _fail('contradictory_binding')
    metadata = sessions['auraface']['actual_output_metadata']
    if len(metadata) != 1:
        _fail('contradictory_binding')
    declared = _canonical_tensor_contract(metadata[0]['shape'], metadata[0]['dtype'], allow_symbolic=True)
    if (declared['dtype'] != 'float32' or len(declared['shape']) != 2
            or any(not isinstance(expected, str) and observed != expected
                   for observed, expected in zip((1, value['raw_output']['dimension']), declared['shape']))):
        _fail('contradictory_binding')
    if abs(value['normalized_output']['norm'] - 1) > 1e-5:
        _fail('incomplete')
    _hex(value['graph_analysis_sha256'])
    if value['graph_analysis_sha256'] != sessions['auraface']['graph_analysis']['analysis_sha256']:
        _fail('contradictory_binding')
    if sessions['auraface']['graph_analysis']['output_l2_normalized'] and abs(value['raw_output']['norm'] - 1) > 1e-5:
        _fail('contradictory_binding')
    for session in sessions.values():
        if _time(session['constructed_at']) > _time(value['captured_at']):
            _fail('contradictory_binding')


def _runtime(value, now, policy):
    _closed(value, 'producer_abi_version runtime_generation_id model_id effective_profile declared_embedding_dimension observed_embedding_dimension preprocessing_id compatibility_sha256 config_sha256 sessions frozen_preprocessing_spec execution_receipt state reason_code observed_at', ('producer_abi_version',))
    for key in ('runtime_generation_id', 'model_id', 'effective_profile', 'preprocessing_id'):
        _text(value[key])
    _hex(value['compatibility_sha256']); _hex(value['config_sha256'])
    _fresh(value['observed_at'], now, policy)
    if value['state'] not in ('not_loaded', 'loaded_unexercised', 'attested', 'drifted', 'failed'):
        _fail('malformed')
    if value['state'] != 'attested' or value['reason_code'] is not None:
        _fail('failed' if value['state'] == 'failed' else 'incomplete')
    if value['declared_embedding_dimension'] != 512 or type(value['declared_embedding_dimension']) is not int or value['observed_embedding_dimension'] != 512 or type(value['observed_embedding_dimension']) is not int:
        _fail('incomplete')
    if not value['model_id'].startswith('auraface+') or value['effective_profile'] != 'auraface':
        _fail('contradictory_binding')
    _closed(value['sessions'], 'yunet auraface')
    for name, session in value['sessions'].items():
        _session(session, value['runtime_generation_id'], name, now, policy)
    if value['sessions']['yunet']['session_id'] == value['sessions']['auraface']['session_id']:
        _fail('contradictory_binding')
    # The spec summary only binds receipt digests; it is not recipe verification.
    spec = value['frozen_preprocessing_spec']
    _closed(spec, 'spec_sha256')
    _hex(spec['spec_sha256'])
    if any(s['frozen_preprocessing_sha256'] != spec['spec_sha256'] for s in value['sessions'].values()):
        _fail('contradictory_binding')
    _execution(value['execution_receipt'], value, now, policy)


def _catalog(value, role, process, now, policy, isolation):
    if value is None:
        _fail('incomplete')
    _closed(value, 'role process_instance_id pool_identity tenant_context_id captured_at collection_status reason_code database_instance_id database_name database_role storage_identity census_complete tenant_coverage_complete vector_columns')
    _status(value); _fresh(value['captured_at'], now, policy)
    if value['role'] != role or value['process_instance_id'] != process:
        _fail('contradictory_binding')
    _text(value['pool_identity'])
    for key in ('tenant_context_id','database_instance_id','database_name','database_role','storage_identity'):
        _text(value[key])
        if value[key] != isolation[key]:
            _fail('contradictory_binding')
    for key in ('census_complete','tenant_coverage_complete'):
        _boolean(value[key])
        if not value[key]:
            _fail('incomplete')
    columns = _list(value['vector_columns'], True)
    seen = set()
    for column in columns:
        _closed(column, 'schema table column dimension row_count model_ids lineage_complete representative_vectors_valid')
        key = tuple(_text(column[k]) for k in ('schema','table','column'))
        if key in seen:
            _fail('contradictory_binding')
        seen.add(key)
        _integer(column['dimension'], 1); _integer(column['row_count'])
        if column['dimension'] != 512:
            _fail('contradictory_binding')
        for model in _list(column['model_ids']):
            if not _text(model).startswith('auraface+'):
                _fail('contradictory_binding')
        for flag in ('lineage_complete','representative_vectors_valid'):
            _boolean(column[flag])
            if not column[flag]:
                _fail('incomplete')
        if column['row_count'] > 0 and not column['model_ids']:
            _fail('incomplete')


def _role(value, now, policy, isolation):
    _closed(value, 'producer_abi_version role process_instance_id observation_sequence captured_at source_identity effective_settings adapter_observations serving_catalog collection_status reason_code', ('producer_abi_version',))
    if value['role'] not in ('api','worker'):
        _fail('malformed')
    _text(value['process_instance_id']); _integer(value['observation_sequence'], 1)
    _status(value); _fresh(value['captured_at'], now, policy); _source(value['source_identity'])
    _closed(value['effective_settings'], 'config_sha256'); _hex(value['effective_settings']['config_sha256'])
    observations = _list(value['adapter_observations'], True)
    ids = set()
    for observation in observations:
        _closed(observation, 'adapter_instance_id usage_origin runtime_record last_execution_at active')
        adapter = _text(observation['adapter_instance_id']); _boolean(observation['active'])
        if adapter in ids:
            _fail('contradictory_binding')
        ids.add(adapter)
        if observation['usage_origin'] != 'serving' or not observation['active']:
            _fail('incomplete')
        _fresh(observation['last_execution_at'], now, policy)
        _runtime(observation['runtime_record'], now, policy)
        if observation['runtime_record']['config_sha256'] != value['effective_settings']['config_sha256']:
            _fail('contradictory_binding')
        if _time(observation['runtime_record']['execution_receipt']['captured_at']) > _time(value['captured_at']) or _time(observation['last_execution_at']) > _time(value['captured_at']):
            _fail('contradictory_binding')
    _catalog(value['serving_catalog'], value['role'], value['process_instance_id'], now, policy, isolation)


def _inputs(value, now, policy, isolation):
    _bounded_json(value)
    _closed(value, 'expected_processes image_records repair_identity previous_observations serving_bindings')
    expected = set()
    for item in _list(value['expected_processes'], True):
        _closed(item, 'role process_instance_id')
        if item['role'] not in ('api','worker'):
            _fail('malformed')
        key = (item['role'], _text(item['process_instance_id']))
        if key in expected:
            _fail('duplicate_role_process')
        expected.add(key)
    if {key[0] for key in expected} != {'api','worker'}:
        _fail('incomplete')
    images = {}
    for item in _list(value['image_records'], True):
        _closed(item, 'role process_instance_id container_id registry_manifest_digest digest_type platform image_config_digest identity_document_sha256 source_identity resource_policy_id')
        _image(item, item['source_identity'], isolation)
        key = (item['role'],item['process_instance_id'])
        if key in images:
            _fail('contradictory_binding')
        images[key] = item
    if set(images) != expected:
        _fail('incomplete')
    bindings = {}
    for item in _list(value['serving_bindings'], True):
        _closed(item, 'role process_instance_id pool_identity')
        key = (_text(item['role']), _text(item['process_instance_id']))
        _text(item['pool_identity'])
        if key in bindings:
            _fail('contradictory_binding')
        bindings[key] = item['pool_identity']
    if set(bindings) != expected:
        _fail('incomplete')
    previous = {}
    for item in _list(value['previous_observations']):
        _closed(item, 'role process_instance_id observation_sequence captured_at record_sha256')
        if item['role'] not in ('api', 'worker'):
            _fail('malformed')
        key = (item['role'],_text(item['process_instance_id']))
        _integer(item['observation_sequence'], 1); _time(item['captured_at']); _hex(item['record_sha256'])
        if key in previous:
            _fail('contradictory_binding')
        previous[key] = item
    repair = value['repair_identity']
    if repair is None:
        _fail('incomplete')
    _closed(repair, 'producer_abi_version role captured_at repair_invocation_id source_identity image_record collection_status reason_code', ('producer_abi_version',))
    if repair['role'] != 'fix-blob-ownership':
        _fail('malformed')
    _text(repair['repair_invocation_id']); _status(repair); _fresh(repair['captured_at'], now, policy); _source(repair['source_identity'])
    _image(repair['image_record'],repair['source_identity'],isolation)
    if repair['image_record']['role'] != repair['role'] or repair['image_record']['process_instance_id'] != repair['repair_invocation_id']:
        _fail('contradictory_binding')
    return expected, images, previous, repair, bindings


def _validate_policy(freshness, isolation, now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    try:
        _closed(freshness, 'max_age_seconds future_skew_seconds')
        for value in freshness.values():
            _number(value)
            if value < 0:
                _fail('malformed')
        _closed(isolation, 'resource_policy_id database_instance_id database_name database_role storage_identity tenant_context_id')
        for value in isolation.values():
            _text(value)
    except RecordError:
        raise ValueError('explicit bounded freshness and isolation policies required') from None


def empty_result():
    return dict(collector_ledger_version=1, status='incomplete', reason_code='acceptance_contract_unavailable', gaps=['GAP-V1-REPAIR','GAP-BRANCH-ARTIFACTS'], acquisition_ledger=[], snapshot=None, sidecar=None)


def join_auraface_acceptance(records, *, captured_inputs, expected_contract,
                             freshness_policy, isolation_policy, now):
    """Join captured observations only; cross-role UUIDs remain independent.

    The ledger's ``joined`` means captured compatibility and identities agree;
    it never means recipe verification, live readiness, or full acceptance.
    Rows preserve local_reason_code separately from aggregate_reason_codes;
    reason_code remains the refusal summary when an aggregate check fails.
    Executed tensor values, preprocessing/alignment/output digests and fixture/reference lineage
    must agree across roles, as must the captured census; disagreement is a
    contradictory_binding. Execution and adapter IDs cannot be shared across
    processes. Executed shapes/dtypes bind to each role's own session metadata,
    including the single batch of 512 output components.
    ORT tensor(float) means float32; metadata symbols match only their own
    concrete tensor dimensions, with equal rank and all concrete dims checked.
    For the same pinned fixture, the full span of raw norms must be within
    RAW_NORM_ABS_TOLERANCE (1e-5 absolute, no relative tolerance); a wider span
    refuses with contradictory_binding, as does any executed digest mismatch.
    A graph-L2 claim requires a unit raw norm in that role's execution receipt;
    agreement of captured values does not establish the graph's property.
    Compact preprocessing/settings/catalog summaries are explicitly limited
    capture contracts, not a substitute for the future full validator ABI.
    """
    if expected_contract != 'candidate512':
        raise ValueError('expected_contract must explicitly be candidate512')
    _validate_policy(freshness_policy, isolation_policy, now)
    result = empty_result()
    gaps = set(result['gaps'])
    if not isinstance(records, (list, tuple)) or len(records) > MAX_RECORDS:
        gaps.add('oversized')
        result['gaps'] = sorted(gaps)
        return result
    try:
        expected, images, previous, repair, bindings = _inputs(captured_inputs, now, freshness_policy, isolation_policy)
    except RecordError as exc:
        gaps.add(str(exc))
        result['gaps'] = sorted(gaps)
        return result
    if set(previous) - expected:
        gaps.add('restarted')
    seen = set()
    fingerprints = set()
    sources = []
    image_contracts = []
    generations = {}
    session_owners = {}
    execution_owners = {}
    adapter_owners = {}
    executed_contracts = set()
    raw_norms = []
    censuses = set()
    for index, record in enumerate(records):
        entry = dict(record_index=index, status='incomplete', reason_code='incomplete', record_sha256=None)
        try:
            entry['record_sha256'] = record_digest(record)
            _role(record, now, freshness_policy, isolation_policy)
            key = (record['role'],record['process_instance_id'])
            if key in seen:
                _fail('duplicate_role_process')
            seen.add(key)
            if key not in expected:
                _fail('restarted' if any(role == key[0] for role, _ in expected) else 'contradictory_binding')
            image = images[key]
            _image(image, record['source_identity'], isolation_policy)
            if key in previous:
                prior = previous[key]
                if record['observation_sequence'] < prior['observation_sequence']:
                    _fail('out_of_order')
                if record['observation_sequence'] == prior['observation_sequence'] and (entry['record_sha256'] != prior['record_sha256'] or record['captured_at'] != prior['captured_at']):
                    _fail('contradictory_binding')
                if _time(record['captured_at']) < _time(prior['captured_at']):
                    _fail('out_of_order')
            sources.append(record['source_identity'])
            image_contracts.append(tuple(image[k] for k in ('registry_manifest_digest','digest_type','platform','image_config_digest')))
            # Pool identity is process-local; a captured prior binds its continuity.
            # A pool is never inferred from a role name or an expected DB pin.
            if record['serving_catalog']['pool_identity'] != bindings[key]:
                _fail('contradictory_binding')
            censuses.add(record_digest(sorted(record['serving_catalog']['vector_columns'],
                key=lambda column: (column['schema'], column['table'], column['column']))))
            for obs in record['adapter_observations']:
                rt = obs['runtime_record']
                execution = rt['execution_receipt']
                for identifier, owners in ((execution['execution_id'], execution_owners),
                                           (obs['adapter_instance_id'], adapter_owners)):
                    if identifier in owners and owners[identifier] != key:
                        _fail('contradictory_binding')
                    owners[identifier] = key
                tensor_contracts = {}
                for tensor_key, fields in (('detector_input', ('sha256', 'padding_geometry')),
                                           ('embedder_input', ('sha256', 'channel_samples', 'mean', 'scale'))):
                    tensor = execution[tensor_key]
                    tensor_contracts[tensor_key] = dict(_canonical_tensor_contract(tensor['shape'], tensor['dtype']),
                                                      **{k: tensor[k] for k in fields})
                executed_contracts.add(record_digest(dict(
                    detector=tensor_contracts['detector_input'],
                    embedder=tensor_contracts['embedder_input'],
                    detections_sha256=execution['detections_sha256'],
                    alignment=execution['alignment'],
                    raw_output_sha256=execution['raw_output']['sha256'],
                    normalized_output_sha256=execution['normalized_output']['sha256'],
                    input_lineage=execution['input_lineage'])))
                raw_norms.append(execution['raw_output']['norm'])
                generation = rt['runtime_generation_id']
                if generation in generations and generations[generation] != key:
                    _fail('contradictory_binding')
                generations[generation] = key
                for session in rt['sessions'].values():
                    sid = session['session_id']
                    owner = (key, generation, session['logical_model_name'])
                    if sid in session_owners and session_owners[sid] != owner:
                        _fail('contradictory_binding')
                    session_owners[sid] = owner
                # Compare captured contract fields, not a producer label alone.
                session_contracts = []
                for name in ('yunet', 'auraface'):
                    contract = {k: v for k, v in rt['sessions'][name].items()
                                if k not in ('session_id', 'runtime_generation_id', 'constructed_at')}
                    for metadata_key in ('actual_input_metadata', 'actual_output_metadata'):
                        contract[metadata_key] = [dict(item, **_canonical_tensor_contract(
                            item['shape'], item['dtype'], allow_symbolic=True)) for item in contract[metadata_key]]
                    session_contracts.append(record_digest(contract))
                fingerprints.add((rt['compatibility_sha256'], rt['model_id'],
                    rt['preprocessing_id'], rt['config_sha256'],
                    record_digest(rt['frozen_preprocessing_spec']), *session_contracts))
            entry['reason_code'] = None
        except RecordError as exc:
            entry['reason_code'] = str(exc); gaps.add(str(exc))
        result['acquisition_ledger'].append(entry)
    if seen != expected:
        gaps.add('incomplete')
    if len(executed_contracts) > 1 or len(censuses) > 1:
        gaps.add('contradictory_binding')
    if raw_norms and _raw_norm_span_exceeds_tolerance(raw_norms):
        gaps.add('contradictory_binding')
    if len(fingerprints) > 1:
        gaps.add('contradictory_binding')
    if any(source != repair['source_identity'] for source in sources):
        gaps.add('contradictory_binding')
    repair_image = repair['image_record']
    repair_contract = tuple(repair_image[k] for k in ('registry_manifest_digest','digest_type','platform','image_config_digest'))
    if any(contract != repair_contract for contract in image_contracts):
        gaps.add('contradictory_binding')
    aggregate_gaps = gaps - {'GAP-V1-REPAIR', 'GAP-BRANCH-ARTIFACTS'}
    for entry in result['acquisition_ledger']:
        entry['local_reason_code'] = entry['reason_code']
        entry['aggregate_reason_codes'] = sorted(aggregate_gaps)
        if entry['reason_code'] is None:
            if aggregate_gaps:
                entry['reason_code'] = 'contradictory_binding' if 'contradictory_binding' in aggregate_gaps else sorted(aggregate_gaps)[0]
            else:
                entry['status'] = 'joined'
    result['gaps'] = sorted(gaps)
    return result
