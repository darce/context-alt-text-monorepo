"""Offline synthetic controls: none of these records are live evidence."""
import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[3] / 'scripts'
NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
STAMP = '2026-10-13T00:00:00+00:00'
H = 'a' * 64


def load(name):
    path = SCRIPTS / (name + '.py')
    if not path.exists():
        pytest.fail('causal RED: owned offline implementation is absent: ' + name)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source():
    return dict(source_identity_version=1, source_git_sha='b' * 40,
                source_tree='c' * 40, build_context_manifest_sha256=H,
                service_lock_sha256=H, image_variant='candidate', build_time=STAMP,
                identity_document_sha256=H)


def runtime(role):
    generation = role + '-generation'
    sessions = {}
    for name in ('yunet', 'auraface'):
        sessions[name] = dict(session_id=role + '-' + name, runtime_generation_id=generation,
            logical_model_name=name, constructed_at=STAMP, observed_weight_sha256=H,
            observed_weight_size_bytes=123, observed_license_sha256=H,
            observed_license_size_bytes=12, manifest_expectation_sha256=H,
            frozen_preprocessing_sha256=H, numeric_runtime_fingerprint=H,
            actual_providers=['CPUExecutionProvider'], actual_input_metadata=[dict(name='input', shape=[1,3,112,112], dtype='float32')],
            actual_output_metadata=[dict(name='output', shape=[1,512], dtype='float32')],
            actual_session_options=dict(intra_op_num_threads=1, inter_op_num_threads=1, execution_mode='sequential', graph_optimization_level='all'),
            graph_analysis=dict(model_sha256=H, analysis_sha256=H, output_l2_normalized=False))
    execution = dict(execution_id=role+'-execution', runtime_generation_id=generation,
        detector_session_id=role+'-yunet', embedder_session_id=role+'-auraface', captured_at=STAMP,
        input_lineage=dict(fixture_id='asymmetric-fixture', fixture_sha256=H, independent_reference_sha256=H),
        detector_input=dict(sha256=H,shape=[1,3,112,112],dtype='float32',contiguous=True,padding_geometry=[0,0,0,0]),
        detections_sha256=H, alignment=dict(landmarks_sha256=H, executing_spec_sha256=H, template_sha256=H, affine_sha256=H,crop_sha256=H),
        embedder_input=dict(sha256=H,shape=[1,3,112,112],dtype='float32',contiguous=True,channel_samples=[1.0,2.0,3.0],mean=127.5,scale=1/128),
        raw_output=dict(sha256=H,dimension=512,norm=2.0),normalized_output=dict(sha256=H,dimension=512,norm=1.0),graph_analysis_sha256=H,completion='complete')
    return dict(producer_abi_version=1,runtime_generation_id=generation,model_id='auraface+synthetic',effective_profile='auraface',declared_embedding_dimension=512,observed_embedding_dimension=512,preprocessing_id='synthetic-arcface',compatibility_sha256=H,config_sha256=H,sessions=sessions,
        frozen_preprocessing_spec=dict(spec_sha256=H),execution_receipt=execution,state='attested',reason_code=None,observed_at=STAMP)


def pair():
    records = []
    images = []
    for role in ('api','worker'):
        process = role+'-process'
        catalog = dict(role=role, process_instance_id=process, pool_identity=role+'-pool',tenant_context_id='tenant-opaque',captured_at=STAMP,collection_status='complete',reason_code=None,
            database_instance_id='instance-opaque',database_name='candidate_store',database_role='serving_role',storage_identity='store-opaque',census_complete=True,tenant_coverage_complete=True,vector_columns=[dict(schema='app',table='vectors',column='embedding',dimension=512,row_count=0,model_ids=[],lineage_complete=True,representative_vectors_valid=True)])
        records.append(dict(producer_abi_version=1,role=role,process_instance_id=process,observation_sequence=1,captured_at=STAMP,source_identity=source(),effective_settings=dict(config_sha256=H),adapter_observations=[dict(adapter_instance_id=role+'-adapter',usage_origin='serving',runtime_record=runtime(role),last_execution_at=STAMP,active=True)],serving_catalog=catalog,collection_status='complete',reason_code=None))
        images.append(dict(role=role,process_instance_id=process,container_id=role+'-container',registry_manifest_digest='sha256:'+H,digest_type='manifest',platform='linux/amd64',image_config_digest='sha256:'+H,identity_document_sha256=H,source_identity=source(),resource_policy_id='candidate-target'))
    repair_image = dict(images[0],role='fix-blob-ownership',process_instance_id='repair-invocation',container_id='repair-container')
    repair = dict(producer_abi_version=1,role='fix-blob-ownership',captured_at=STAMP,repair_invocation_id='repair-invocation',source_identity=source(),image_record=repair_image,collection_status='complete',reason_code=None)
    inputs = dict(expected_processes=[dict(role=r['role'],process_instance_id=r['process_instance_id']) for r in records],image_records=images,repair_identity=repair,previous_observations=[],serving_bindings=[dict(role=r['role'],process_instance_id=r['process_instance_id'],pool_identity=r['serving_catalog']['pool_identity']) for r in records])
    return records, inputs


def join(records, inputs):
    return load('auraface_acceptance_join').join_auraface_acceptance(records,captured_inputs=inputs,expected_contract='candidate512',freshness_policy=dict(max_age_seconds=60,future_skew_seconds=2),isolation_policy=dict(resource_policy_id='candidate-target',database_instance_id='instance-opaque',database_name='candidate_store',database_role='serving_role',storage_identity='store-opaque',tenant_context_id='tenant-opaque'),now=NOW)


def test_healthy_pair_with_different_role_generations_preserves_contract_gap():
    records, inputs = pair()
    before = copy.deepcopy((records, inputs))
    result = join(records,inputs)
    assert result['collector_ledger_version'] == 1
    assert result['snapshot'] is None and result['sidecar'] is None
    assert result['status'] == 'incomplete'
    assert set(result['gaps']) == {'GAP-V1-REPAIR','GAP-BRANCH-ARTIFACTS'}
    assert (records,inputs) == before


@pytest.mark.parametrize('field', ['source_tree','source_git_sha','build_context_manifest_sha256','service_lock_sha256','identity_document_sha256'])
def test_observations_never_backfilled_from_policy(field):
    records, inputs = pair()
    del records[0]['source_identity'][field]
    result = join(records,inputs)
    assert 'incomplete' in result['gaps']
    assert result['snapshot'] is None


@pytest.mark.parametrize('value',[True,False,2,None,'1'])
def test_incompatible_versions(value):
    records, inputs = pair()
    records[0]['producer_abi_version'] = value
    assert 'incompatible_version' in join(records,inputs)['gaps']


@pytest.mark.parametrize('target',['role','source','session','execution','catalog'])
def test_closed_records(target):
    records, inputs = pair()
    node = {'role':records[0],'source':records[0]['source_identity'],'session':records[0]['adapter_observations'][0]['runtime_record']['sessions']['yunet'],'execution':records[0]['adapter_observations'][0]['runtime_record']['execution_receipt'],'catalog':records[0]['serving_catalog']}[target]
    node['unexpected'] = 'rejected-sentinel'
    result = join(records,inputs)
    assert 'malformed' in result['gaps']
    assert 'rejected-sentinel' not in str(result)


@pytest.mark.parametrize('factor',['generation','session','compatibility','tree','build','lock','digest_type','platform','image','resource','instance','database','db_role','tenant','pool','constructed','unexercised','width','norm','graph','replica','stale','future','duplicate','sequence','restart'])
def test_independent_join_contradictions(factor):
    records, inputs = pair()
    r = records[0]; rt = r['adapter_observations'][0]['runtime_record']
    if factor == 'generation': rt['execution_receipt']['runtime_generation_id'] = 'other'
    elif factor == 'session': rt['execution_receipt']['detector_session_id'] = 'other'
    elif factor == 'compatibility': rt['compatibility_sha256'] = 'd'*64
    elif factor in ('tree','build','lock'): r['source_identity'][{'tree':'source_tree','build':'build_context_manifest_sha256','lock':'service_lock_sha256'}[factor]] = 'd'*(40 if factor=='tree' else 64)
    elif factor == 'digest_type': inputs['image_records'][0]['digest_type'] = 'index'
    elif factor == 'platform': inputs['image_records'][0]['platform'] = 'linux/arm64'
    elif factor == 'image': inputs['image_records'][0]['image_config_digest'] = 'sha256:'+'d'*64
    elif factor == 'resource': inputs['image_records'][0]['resource_policy_id'] = 'other'
    elif factor in ('instance','database','db_role','tenant','pool'): r['serving_catalog'][{'instance':'database_instance_id','database':'database_name','db_role':'database_role','tenant':'tenant_context_id','pool':'pool_identity'}[factor]] = 'other'
    elif factor == 'constructed': rt['state'] = 'loaded_unexercised'
    elif factor == 'unexercised': rt['execution_receipt'] = None
    elif factor == 'width': rt['observed_embedding_dimension'] = 128
    elif factor == 'norm': rt['execution_receipt']['normalized_output']['norm'] = 2.0
    elif factor == 'graph': rt['sessions']['auraface']['graph_analysis'] = None
    elif factor == 'replica': inputs['expected_processes'].append(dict(role='worker',process_instance_id='missing-replica'))
    elif factor == 'stale': r['captured_at'] = '2026-10-12T00:00:00+00:00'
    elif factor == 'future': r['captured_at'] = '2026-10-14T00:00:00+00:00'
    elif factor == 'duplicate': records.append(copy.deepcopy(r))
    elif factor == 'sequence': inputs['previous_observations'] = [dict(role='api',process_instance_id='api-process',observation_sequence=2,captured_at=STAMP,record_sha256='d'*64)]
    elif factor == 'restart':
        r['process_instance_id'] = 'restarted-process'
        r['serving_catalog']['process_instance_id'] = 'restarted-process'
    result = join(records,inputs)
    expected = {
        'constructed':'incomplete', 'unexercised':'incomplete', 'width':'incomplete',
        'norm':'incomplete', 'graph':'incomplete', 'replica':'incomplete',
        'stale':'stale', 'future':'future_clock', 'duplicate':'duplicate_role_process',
        'sequence':'out_of_order', 'restart':'restarted',
    }.get(factor, 'contradictory_binding')
    assert expected in result['gaps']
    if factor not in ('replica', 'duplicate', 'restart', 'resource'):
        assert result['acquisition_ledger'][0]['reason_code'] == expected
    assert result['snapshot'] is None


def test_contract_must_be_explicit():
    records, inputs = pair()
    module = load('auraface_acceptance_join')
    with pytest.raises(ValueError,match='candidate512'):
        module.join_auraface_acceptance(records,captured_inputs=inputs,expected_contract='baseline128',freshness_policy={},isolation_policy={},now=NOW)


@pytest.mark.parametrize('location',['source','runtime','repair'])
@pytest.mark.parametrize('version',[True,2,None,'1','missing'])
def test_every_nested_version_is_strict(location,version):
    records,inputs=pair()
    node,key={'source':(records[0]['source_identity'],'source_identity_version'),'runtime':(records[0]['adapter_observations'][0]['runtime_record'],'producer_abi_version'),'repair':(inputs['repair_identity'],'producer_abi_version')}[location]
    if version=='missing': del node[key]
    else: node[key]=version
    assert 'incompatible_version' in join(records,inputs)['gaps']


def test_identical_repeat_is_allowed_without_refresh():
    records,inputs=pair()
    module=load('auraface_acceptance_join')
    inputs['previous_observations']=[dict(role='api',process_instance_id='api-process',observation_sequence=1,captured_at=STAMP,record_sha256=module.record_digest(records[0]))]
    assert set(join(records,inputs)['gaps'])=={'GAP-V1-REPAIR','GAP-BRANCH-ARTIFACTS'}


def test_same_sequence_changed_content_is_contradictory():
    records,inputs=pair()
    module=load('auraface_acceptance_join')
    digest=module.record_digest(records[0])
    inputs['previous_observations']=[dict(role='api',process_instance_id='api-process',observation_sequence=1,captured_at=STAMP,record_sha256=digest)]
    records[0]['adapter_observations'][0]['adapter_instance_id']='changed-adapter'
    assert 'contradictory_binding' in join(records,inputs)['gaps']


def test_policy_pins_cannot_supply_a_missing_execution():
    records,inputs=pair()
    records[0]['adapter_observations'][0]['runtime_record']['execution_receipt']=None
    assert 'incomplete' in join(records,inputs)['gaps']


def test_pool_binds_to_independently_captured_serving_connection():
    records,inputs=pair()
    records[0]['serving_catalog']['pool_identity']='observability-pool'
    assert 'contradictory_binding' in join(records,inputs)['gaps']


def test_runtime_ids_reused_across_roles_are_refused():
    records,inputs=pair()
    records[1]['adapter_observations'][0]['runtime_record']=copy.deepcopy(records[0]['adapter_observations'][0]['runtime_record'])
    assert 'contradictory_binding' in join(records,inputs)['gaps']


@pytest.mark.parametrize('field',['numeric_runtime_fingerprint','manifest_expectation_sha256','actual_input_metadata','observed_weight_size_bytes','graph_analysis'])
def test_compatibility_label_cannot_hide_changed_session_contract(field):
    records,inputs=pair()
    session=records[0]['adapter_observations'][0]['runtime_record']['sessions']['yunet']
    if field=='actual_input_metadata': session[field][0]['shape'][2]=224
    elif field=='observed_weight_size_bytes': session[field]+=1
    elif field=='graph_analysis': session[field]['output_l2_normalized']=True
    else: session[field]='d'*64
    assert 'contradictory_binding' in join(records,inputs)['gaps']


def test_inventory_restart_discontinuity_is_explicit():
    records,inputs=pair()
    inputs['previous_observations']=[dict(role='api',process_instance_id='old-process',observation_sequence=8,captured_at=STAMP,record_sha256=H)]
    assert 'restarted' in join(records,inputs)['gaps']


def test_nonfinite_and_huge_values_are_sanitized():
    records,inputs=pair()
    records[0]['observation_sequence']=10**2000
    assert 'malformed' in join(records,inputs)['gaps']


def test_partial_execution_cannot_be_promoted_by_complete_envelope():
    records,inputs=pair()
    records[0]['adapter_observations'][0]['runtime_record']['execution_receipt']['completion']='no_face'
    assert 'incomplete' in join(records,inputs)['gaps']


def test_nondict_image_is_sanitized():
    records, inputs = pair()
    inputs['image_records'][0] = 'fixture-canary'
    result = join(records, inputs)
    assert set(result['gaps']) == {'GAP-V1-REPAIR', 'GAP-BRANCH-ARTIFACTS', 'malformed'}
    assert 'fixture-canary' not in str(result)


def test_absent_source_is_incomplete():
    records, inputs = pair()
    records[0]['source_identity'] = None
    result = join(records, inputs)
    assert 'incomplete' in result['gaps'] and 'malformed' not in result['gaps']


BASE_GAPS = {'GAP-V1-REPAIR', 'GAP-BRANCH-ARTIFACTS'}
OLD = '2026-10-12T23:58:00+00:00'


def assert_gap(records, inputs, code, row=None):
    result = join(records, inputs)
    assert code in result['gaps']
    assert set(result['gaps']) - BASE_GAPS <= {code, 'incomplete'}
    assert result['snapshot'] is None and result['sidecar'] is None
    if row is not None:
        assert result['acquisition_ledger'][row]['reason_code'] == code
    assert all(item['status'] != 'joined' for item in result['acquisition_ledger'])


@pytest.mark.parametrize('factor,code', [
    ('catalog_stale','stale'), ('role_incomplete','incomplete'),
    ('image_source','contradictory_binding'), ('session_generation','contradictory_binding'),
    ('graph_model','contradictory_binding'), ('contiguous','incomplete'),
    ('execution_stale','stale'), ('executing_spec','contradictory_binding'),
    ('model_prefix','contradictory_binding'), ('frozen_spec','contradictory_binding'),
    ('census','incomplete'), ('column128','contradictory_binding'),
    ('health_probe_only','incomplete'), ('config','contradictory_binding'),
    ('missing_worker','incomplete'), ('repair_role','malformed'),
    ('repair_image_role','contradictory_binding'), ('repair_image_process','contradictory_binding'),
    ('generation_reuse','contradictory_binding'), ('session_reuse','contradictory_binding'),
    ('missing_record','incomplete'), ('source_cross_role','contradictory_binding'),
    ('catalog_model_prefix','contradictory_binding'), ('lineage','incomplete'),
    ('representative','incomplete'), ('tenant_coverage','incomplete'),
    ('row_models','incomplete'), ('catalog_binding','contradictory_binding'),
    ('graph_digest','contradictory_binding'), ('usage_origin','incomplete'),
    ('inactive','incomplete'), ('execution_id_reuse','contradictory_binding'),
    ('adapter_id_reuse','contradictory_binding'), ('census_disagreement','contradictory_binding'),
])
def test_dedicated_join_guard(factor, code):
    records, inputs = pair()
    r = records[0]; obs = r['adapter_observations'][0]; rt = obs['runtime_record']
    ex = rt['execution_receipt']; cat = r['serving_catalog']
    worker = records[1]['adapter_observations'][0]['runtime_record']
    if factor == 'catalog_stale': cat['captured_at'] = OLD
    elif factor == 'role_incomplete': r['collection_status'] = 'incomplete'
    elif factor == 'image_source': inputs['image_records'][0]['source_identity']['source_tree'] = 'd'*40
    elif factor == 'session_generation': rt['sessions']['yunet']['runtime_generation_id'] = 'other'
    elif factor == 'graph_model': rt['sessions']['auraface']['graph_analysis']['model_sha256'] = 'd'*64
    elif factor == 'contiguous': ex['embedder_input']['contiguous'] = False
    elif factor == 'execution_stale':
        ex['captured_at'] = OLD
        for session in rt['sessions'].values(): session['constructed_at'] = OLD
    elif factor == 'executing_spec':
        for record in records: record['adapter_observations'][0]['runtime_record']['execution_receipt']['alignment']['executing_spec_sha256'] = 'd'*64
    elif factor == 'model_prefix':
        for record in records: record['adapter_observations'][0]['runtime_record']['model_id'] = 'insightface+synthetic'
    elif factor == 'frozen_spec':
        for record in records:
            runtime = record['adapter_observations'][0]['runtime_record']
            for session in runtime['sessions'].values(): session['frozen_preprocessing_sha256'] = 'd'*64
            runtime['execution_receipt']['alignment']['executing_spec_sha256'] = 'd'*64
    elif factor in ('census','tenant_coverage'): cat[{'census':'census_complete','tenant_coverage':'tenant_coverage_complete'}[factor]] = False
    elif factor in ('column128','catalog_model_prefix','lineage','representative','row_models'):
        for record in records:
            column = record['serving_catalog']['vector_columns'][0]
            if factor == 'column128': column['dimension'] = 128
            elif factor == 'catalog_model_prefix': column.update(row_count=1,model_ids=['insightface+synthetic'])
            elif factor == 'lineage': column['lineage_complete'] = False
            elif factor == 'representative': column['representative_vectors_valid'] = False
            else: column['row_count'] = 1
    elif factor in ('health_probe_only','usage_origin'): obs['usage_origin'] = 'health_probe_only' if factor == 'health_probe_only' else 'other'
    elif factor == 'inactive': obs['active'] = False
    elif factor == 'config':
        for record in records: record['adapter_observations'][0]['runtime_record']['config_sha256'] = 'd'*64
    elif factor == 'missing_worker':
        records.pop()
        for field in ('expected_processes','image_records','serving_bindings'): inputs[field].pop()
    elif factor == 'repair_role': inputs['repair_identity']['role'] = 'api'
    elif factor == 'repair_image_role': inputs['repair_identity']['image_record']['role'] = 'api'
    elif factor == 'repair_image_process': inputs['repair_identity']['image_record']['process_instance_id'] = 'other'
    elif factor == 'generation_reuse':
        worker['runtime_generation_id'] = rt['runtime_generation_id']
        worker['execution_receipt']['runtime_generation_id'] = rt['runtime_generation_id']
        for session in worker['sessions'].values(): session['runtime_generation_id'] = rt['runtime_generation_id']
    elif factor == 'session_reuse':
        worker['sessions']['yunet']['session_id'] = rt['sessions']['yunet']['session_id']
        worker['execution_receipt']['detector_session_id'] = rt['sessions']['yunet']['session_id']
    elif factor == 'missing_record': records.pop()
    elif factor == 'source_cross_role':
        records[1]['source_identity']['source_tree'] = 'd'*40
        inputs['image_records'][1]['source_identity']['source_tree'] = 'd'*40
    elif factor == 'catalog_binding': cat['role'] = 'worker'
    elif factor == 'graph_digest': ex['graph_analysis_sha256'] = 'd'*64
    elif factor == 'execution_id_reuse': worker['execution_receipt']['execution_id'] = ex['execution_id']
    elif factor == 'adapter_id_reuse': records[1]['adapter_observations'][0]['adapter_instance_id'] = obs['adapter_instance_id']
    elif factor == 'census_disagreement': records[1]['serving_catalog']['vector_columns'][0].update(row_count=7,model_ids=['auraface+other'])
    assert_gap(records, inputs, code)


@pytest.mark.parametrize('site', ['role','runtime','execution','adapter','catalog','repair'])
def test_each_timestamp_staleness(site):
    records, inputs = pair()
    r = records[0]; obs = r['adapter_observations'][0]; rt = obs['runtime_record']
    ex = rt['execution_receipt']
    node, key = {'role':(r,'captured_at'), 'runtime':(rt,'observed_at'),
        'execution':(ex,'captured_at'), 'adapter':(obs,'last_execution_at'),
        'catalog':(r['serving_catalog'],'captured_at'),
        'repair':(inputs['repair_identity'],'captured_at')}[site]
    node[key] = OLD
    if site in ('role','execution'):
        for session in rt['sessions'].values(): session['constructed_at'] = OLD
    assert_gap(records, inputs, 'stale')


@pytest.mark.parametrize('factor', ['mean','scale','channel_samples','template','detector_shape',
    'embedder_shape','detector_dtype','embedder_dtype','fixture_id','fixture_sha256',
    'independent_reference_sha256','graph_l2'])
def test_executed_value_binding(factor):
    records, inputs = pair()
    rt = records[1]['adapter_observations'][0]['runtime_record']; ex = rt['execution_receipt']
    if factor == 'mean': ex['embedder_input']['mean'] = 0.0
    elif factor == 'scale': ex['embedder_input']['scale'] = 1.0
    elif factor == 'channel_samples': ex['embedder_input']['channel_samples'].reverse()
    elif factor == 'template': ex['alignment']['template_sha256'] = 'd'*64
    elif factor.endswith('_shape'):
        for record in records:
            record['adapter_observations'][0]['runtime_record']['execution_receipt'][factor.split('_')[0]+'_input']['shape'][2] = 224
    elif factor.endswith('_dtype'):
        # Change both role-local session declarations, eliminating cross-role
        # session mismatch; executed float32 must still contradict its own session.
        name = 'yunet' if factor.startswith('detector') else 'auraface'
        for record in records:
            record['adapter_observations'][0]['runtime_record']['sessions'][name]['actual_input_metadata'][0]['dtype'] = 'float16'
    elif factor == 'graph_l2':
        for record in records: record['adapter_observations'][0]['runtime_record']['sessions']['auraface']['graph_analysis']['output_l2_normalized'] = True
    else: ex['input_lineage'][factor] = 'other-fixture' if factor == 'fixture_id' else 'd'*64
    assert_gap(records, inputs, 'contradictory_binding')


def test_graph_l2_unit_raw_norm_control():
    records, inputs = pair()
    for record in records:
        rt = record['adapter_observations'][0]['runtime_record']
        rt['sessions']['auraface']['graph_analysis']['output_l2_normalized'] = True
        rt['execution_receipt']['raw_output']['norm'] = 1.0
    assert set(join(records,inputs)['gaps']) == BASE_GAPS


@pytest.mark.parametrize('helper,value,code', [
    ('_text',None,'incomplete'), ('_text',17,'malformed'), ('_text','', 'malformed'),
    ('_text','x'*513,'malformed'), ('_text','fixture@canary','malformed'),
    ('_hex','a'*63,'malformed'), ('_hex','g'*64,'malformed'),
    ('_integer',True,'malformed'), ('_integer',-1,'malformed'),
    ('_integer',2**64,'malformed'), ('_number',True,'malformed'),
    ('_number',float('inf'),'malformed'), ('_number',2**64,'malformed'),
    ('_boolean',1,'malformed'), ('_time','invalid','malformed'),
    ('_time','2026-10-13T00:00:00','malformed'),
    ('_list',{},'malformed'), ('_list',[0]*513,'malformed'),
    ('_source',None,'incomplete'),
    ('_bounded_json',{1:'value'},'malformed'),
    ('_bounded_json',object(),'malformed'),
])
def test_transport_scalar_refusals(helper, value, code):
    module = load('auraface_acceptance_join')
    with pytest.raises(module.RecordError, match='^'+code+'$'):
        getattr(module,helper)(value)


@pytest.mark.parametrize('factor,code', [
    ('closed_nondict','malformed'), ('positive_zero','incomplete'),
    ('empty_list','incomplete'), ('json_nodes','oversized'), ('json_depth','oversized'),
])
def test_transport_structural_refusals(factor, code):
    module = load('auraface_acceptance_join')
    with pytest.raises(module.RecordError, match='^'+code+'$'):
        if factor == 'closed_nondict': module._closed('fixture','field')
        elif factor == 'positive_zero': module._number(0,positive=True)
        elif factor == 'empty_list': module._list([],True)
        elif factor == 'json_nodes': module._bounded_json([[0]*512 for _ in range(100)])
        elif factor == 'json_depth':
            value = 0
            for _ in range(25): value = [value]
            module._bounded_json(value)


@pytest.mark.parametrize('factor,code', [
    ('status_unknown','malformed'), ('status_reason','incomplete'),
    ('image_digest','malformed'), ('image_digest_type','malformed'),
    ('session_future','future_clock'), ('tensor_dtype','incomplete'),
    ('output_width','contradictory_binding'), ('runtime_state','malformed'),
    ('same_sessions','contradictory_binding'), ('catalog_duplicate','contradictory_binding'),
    ('role_name','malformed'), ('duplicate_adapter','contradictory_binding'),
    ('execution_after_capture','contradictory_binding'),
    ('construction_after_execution','contradictory_binding'),
    ('inventory_role','malformed'), ('inventory_duplicate','duplicate_role_process'),
    ('image_duplicate','contradictory_binding'), ('image_missing','incomplete'),
    ('binding_duplicate','contradictory_binding'), ('binding_missing','incomplete'),
    ('previous_role','malformed'), ('previous_duplicate','contradictory_binding'),
    ('repair_missing','incomplete'), ('capture_out_of_order','out_of_order'),
])
def test_additional_join_guard(factor, code):
    records, inputs = pair()
    r=records[0]; obs=r['adapter_observations'][0]; rt=obs['runtime_record']; ex=rt['execution_receipt']
    if factor == 'status_unknown': r['collection_status']='unknown'
    elif factor == 'status_reason': r['reason_code']='fixture-reason'
    elif factor == 'image_digest': inputs['image_records'][0]['registry_manifest_digest']=H
    elif factor == 'image_digest_type': inputs['image_records'][0]['digest_type']='other'
    elif factor == 'session_future': rt['sessions']['yunet']['constructed_at']='2026-10-13T00:00:03+00:00'
    elif factor == 'tensor_dtype': ex['embedder_input']['dtype']='float16'
    elif factor == 'output_width': ex['raw_output']['dimension']=128
    elif factor == 'runtime_state': rt['state']='unknown'
    elif factor == 'same_sessions':
        rt['sessions']['auraface']['session_id']=rt['sessions']['yunet']['session_id']
        ex['embedder_session_id']=rt['sessions']['yunet']['session_id']
    elif factor == 'catalog_duplicate': r['serving_catalog']['vector_columns']*=2
    elif factor == 'role_name': r['role']='other'
    elif factor == 'duplicate_adapter': r['adapter_observations'].append(copy.deepcopy(obs))
    elif factor == 'execution_after_capture': ex['captured_at']='2026-10-13T00:00:01+00:00'
    elif factor == 'construction_after_execution': rt['sessions']['yunet']['constructed_at']='2026-10-13T00:00:01+00:00'
    elif factor == 'inventory_role': inputs['expected_processes'][0]['role']='other'
    elif factor == 'inventory_duplicate': inputs['expected_processes'].append(copy.deepcopy(inputs['expected_processes'][0]))
    elif factor == 'image_duplicate': inputs['image_records'].append(copy.deepcopy(inputs['image_records'][0]))
    elif factor == 'image_missing': inputs['image_records'].pop()
    elif factor == 'binding_duplicate': inputs['serving_bindings'].append(copy.deepcopy(inputs['serving_bindings'][0]))
    elif factor == 'binding_missing': inputs['serving_bindings'].pop()
    elif factor in ('previous_role','previous_duplicate'):
        prior=dict(role='api',process_instance_id='api-process',observation_sequence=1,captured_at=STAMP,record_sha256=H)
        if factor=='previous_role': prior['role']='other'
        inputs['previous_observations']=[prior] if factor=='previous_role' else [prior,copy.deepcopy(prior)]
    elif factor == 'repair_missing': inputs['repair_identity']=None
    elif factor == 'capture_out_of_order':
        inputs['previous_observations']=[dict(role='api',process_instance_id='api-process',observation_sequence=1,captured_at='2026-10-13T00:00:01+00:00',record_sha256=H)]
        r['observation_sequence']=2
    assert_gap(records, inputs, code)


def test_role_local_session_ids_are_distinct_before_aggregate_join():
    module = load('auraface_acceptance_join')
    rt = runtime('api')
    rt['sessions']['auraface']['session_id'] = rt['sessions']['yunet']['session_id']
    rt['execution_receipt']['embedder_session_id'] = rt['sessions']['yunet']['session_id']
    with pytest.raises(module.RecordError,match='^contradictory_binding$'):
        module._runtime(rt,NOW,dict(max_age_seconds=60,future_skew_seconds=2))


def test_missing_catalog_cannot_be_joined():
    records, inputs = pair()
    records[0]['serving_catalog'] = None
    assert_gap(records,inputs,'incomplete',row=0)


@pytest.mark.parametrize('records', [None, {}, [None]*129])
def test_record_inventory_is_bounded(records):
    _, inputs = pair()
    result = join(records,inputs)
    assert set(result['gaps']) == BASE_GAPS | {'oversized'}
    assert result['acquisition_ledger'] == []


@pytest.mark.parametrize('policy', ['negative_age','negative_skew','naive_now'])
def test_explicit_policy_validation(policy):
    records, inputs = pair()
    module = load('auraface_acceptance_join')
    freshness = dict(max_age_seconds=60,future_skew_seconds=2)
    if policy == 'negative_age': freshness['max_age_seconds'] = -1
    elif policy == 'negative_skew': freshness['future_skew_seconds'] = -1
    with pytest.raises(ValueError):
        module.join_auraface_acceptance(records,captured_inputs=inputs,
            expected_contract='candidate512',freshness_policy=freshness,
            isolation_policy=dict(resource_policy_id='candidate-target',database_instance_id='instance-opaque',
                database_name='candidate_store',database_role='serving_role',storage_identity='store-opaque',tenant_context_id='tenant-opaque'),
            now=NOW.replace(tzinfo=None) if policy == 'naive_now' else NOW)
