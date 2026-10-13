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
    elif factor == 'restart': r['process_instance_id'] = 'restarted-process'
    result = join(records,inputs)
    assert set(result['gaps']) - {'GAP-V1-REPAIR','GAP-BRANCH-ARTIFACTS'}
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
