"""Exact pending selection and offline admission; never execute emitted programs."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import prepare_qwen_ab as p
import run_qwen_cohort_operation as caller

REF = Path(__file__).resolve().parent.parent / 'references'
SUPPLIED = REF.parent.parent / 'references'
INVENTORY = SUPPLIED / 'missing/MISSING-ID-PREP.json'
DOC = json.loads(INVENTORY.read_bytes())
NAMES = {'gsq': 'LEXICON-QWEN-GSQ-MISSING-C064-R1', 'ud': 'LEXICON-QWEN-UD-MISSING-04-R1'}
IDS = {'gsq': ['c064'], 'ud': ['c055', 'c061', 'c062', 'c071']}


def make(candidate='gsq', **kw):
    args = dict(missing_inventory=INVENTORY,
                protocol_sha256=DOC['official_protocol_sha256'], corpus_sha256=DOC['active_manifest_sha256'])
    args.update(kw)
    return p.prepare(REF, candidate, 'missing', NAMES[candidate],
                     'workbay-bakeoff-qwen-'+candidate+'-missing-r1.scope', **args)


@pytest.mark.parametrize('candidate', ['gsq', 'ud'])
def test_exact_selection_and_offline_caller(candidate):
    recipe, r = make(candidate)
    assert r['total_distinct_images'] == len(IDS[candidate])
    assert r['completion_POST_budget'] == 3*len(IDS[candidate])
    assert r['per_image_POST_cap'] == 3 and r['whole_client_seconds'] == 420
    assert r['missing_only']['selected_ids'] == IDS[candidate]
    assert r['missing_only']['prespecified_target'] == (120 if candidate == 'gsq' else 30)
    assert r['no_execution'] is True
    pins = caller.embedded_configs(recipe.encode())
    images = []
    for name, pin in pins.items():
        selected = json.loads(base64.b64decode(pin['b64']))
        original = json.loads((REF/'batch-configs'/name).read_bytes())
        assert dict(selected, images=[]) == dict(original, images=[])
        for im in selected['images']:
            assert im == next(i for i in original['images'] if i['image_id'] == im['image_id'])
            images.append(im['image_id'])
    assert images == IDS[candidate]
    assert caller.verify_prepared(r, recipe.encode()).startswith('/tmp/qwen-owner-window.')
    caller.pilot_requirement(r, 'actual-accepted-pilot')
    with pytest.raises(ValueError):
        caller.pilot_requirement(r, None)
    compile(recipe, '<offline>', 'exec')


def test_total_is_fifteen_planned_only():
    assert sum(make(c)[1]['completion_POST_budget'] for c in IDS) == 15


@pytest.mark.parametrize('bad', ['c007', 'c010', 'c051', 'c001', 'unknown', 'c055'])
def test_cannot_select_errors_completed_unknown_or_wrong_model(tmp_path, bad):
    doc = copy.deepcopy(DOC)
    doc['model_rows'][0]['missing_ids'] = [bad]
    path = tmp_path/'inventory.json'; path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        make(missing_inventory=path)


@pytest.mark.parametrize('mutation', ['duplicate', 'model', 'hash', 'path', 'flag'])
def test_inventory_drift_refuses(tmp_path, mutation):
    doc = copy.deepcopy(DOC); row = doc['model_rows'][0]
    if mutation == 'duplicate': row['missing_ids'] *= 2
    if mutation == 'model': row['model_key'] = 'qwen-ud'
    if mutation == 'hash': row['input_records'][0]['sha256'] = '0'*64
    if mutation == 'path': row['input_records'][0]['path'] = 'outside/image.jpg'
    if mutation == 'flag': doc['arbitrary_rows'] = True
    path = tmp_path/'inventory.json'; path.write_text(json.dumps(doc))
    with pytest.raises(ValueError): make(missing_inventory=path)


@pytest.mark.parametrize('kw', [dict(protocol_sha256='0'*64), dict(corpus_sha256='0'*64),
                               dict(cohorts=['qwen-gsq-05.json']), dict(client_seconds=421)])
def test_missing_preconditions(kw):
    with pytest.raises(ValueError): make(**kw)


@pytest.mark.parametrize('key,value', [('candidate','ud'), ('total_distinct_images',True),
    ('completion_POST_budget',15), ('per_image_POST_cap',4), ('whole_client_seconds',421),
    ('gate_token','0'*64), ('sources',{}), ('immutable_candidate_configs',{}),
    ('configs',{}), ('no_execution',False), ('model_contract',{}), ('resource_contracts',{})])
def test_caller_rejects_tampered_receipts(key, value):
    recipe, r = make(); r[key] = value
    with pytest.raises(ValueError): caller.verify_prepared(r, recipe.encode())


def test_caller_rejects_inventory_receipt_tamper():
    recipe, r = make(); r['missing_only']['selected_ids'] = ['c007']
    with pytest.raises(ValueError): caller.verify_prepared(r, recipe.encode())


@pytest.mark.parametrize('candidate,mode,kw', [('gsq','pilot',{}), ('ud','pilot',{}),
    ('gsq','full',dict(cohorts=['qwen-gsq-05.json'])),
    ('ud','full',dict(cohorts=['qwen-ud-01.json','qwen-ud-02.json']))])
def test_legacy_byte_parity(candidate, mode, kw):
    spec = importlib.util.spec_from_file_location('qualified_baseline', SUPPLIED/'qwen-ab/workspace/prepare_qwen_ab.py')
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    args = (REF,candidate,mode,'QWEN-PARITY-R1','workbay-parity.scope')
    a, ar = old.prepare(*args,**kw); b, br = p.prepare(*args,**kw)
    assert a == b
    ar.pop('preparer_sha256'); br.pop('preparer_sha256')
    assert ar == br


def test_settler_accepts_only_exact_missing_names():
    sys.path.insert(0, str(REF.parent/'tools'))
    import settle_qwen_candidate as s
    for c, name in NAMES.items():
        assert s.identity(name)[0] == c
        recipe,r = make(c); r['source_binding'] = caller.source_binding(recipe.encode())
        pins = caller.embedded_configs(recipe.encode())
        configs = {n:base64.b64decode(pin['b64']) for n,pin in pins.items()}
        assert s.prepared_contract(name,r,configs) == (c,len(IDS[c]))
        s.validate_recipe_binding(recipe.encode(),r)
    for name in ['LEXICON-QWEN-UD-MISSING-120-R1','LEXICON-QWEN-GSQ-MISSING-C007-R1']:
        with pytest.raises(s.Refused): s.identity(name)


def test_accepted_gsq_pilot_recipe_is_byte_identical():
    recipe, _ = p.prepare(REF, 'gsq', 'pilot', 'LEXICON-QWEN-GSQ-PILOT-R6',
                         'workbay-bakeoff-lexicon-qwen-gsq-pilot-r6-20261021.scope')
    actual = (SUPPLIED/'LEXICON-QWEN-GSQ-PILOT-R6.remote.py').read_bytes()
    assert recipe.encode() == actual
    custody = json.loads((SUPPLIED/'official/qwen-gsq-pilot-r6-final-custody.json').read_bytes())
    assert p.sha(actual) == custody['recipe_sha256']


def test_replacement_byte_parity(tmp_path):
    from test_prepare_qwen_ab import revision_record
    spec = importlib.util.spec_from_file_location('qualified_replacement_baseline', SUPPLIED/'qwen-ab/workspace/prepare_qwen_ab.py')
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    path = tmp_path/'revision.json'; path.write_text(json.dumps(revision_record()))
    from unittest.mock import patch
    with patch.object(p, 'R2_REVISION_SHA256', p.sha(path.read_bytes())), patch.object(old, 'R2_REVISION_SHA256', p.sha(path.read_bytes())):
        args = (REF,'gsq','replacement','QWEN-PARITY-R1','workbay-parity.scope')
        a,ar = old.prepare(*args,revision=path); b,br = p.prepare(*args,revision=path)
    assert a == b
    ar.pop('preparer_sha256'); br.pop('preparer_sha256'); assert ar == br


def test_rehashed_recipe_tamper_refuses():
    recipe,r = make()
    recipe += '\n# changed after preparation\n'
    r['recipe_sha256'] = p.sha(recipe.encode())
    with pytest.raises(ValueError): caller.verify_prepared(r, recipe.encode())


def test_unknown_cli_flag_refuses(tmp_path):
    result = subprocess.run([sys.executable, str(Path(p.__file__)), '--references',str(REF),
        '--candidate','gsq','--mode','missing','--name',NAMES['gsq'],
        '--unit','workbay-bakeoff-test.scope','--out',str(tmp_path/'out'), '--select-id','c007'],
        capture_output=True,text=True)
    assert result.returncode == 2 and 'unrecognized arguments' in result.stderr
    assert not (tmp_path/'out').exists()


def test_actual_pilot_reuse_proof_and_tamper_refusal():
    spec = importlib.util.spec_from_file_location('qualified_pilot_baseline', SUPPLIED/'qwen-ab/workspace/prepare_qwen_ab.py')
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    _, pr = old.prepare(REF,'gsq','pilot','LEXICON-QWEN-GSQ-PILOT-R6',
                        'workbay-bakeoff-lexicon-qwen-gsq-pilot-r6-20261021.scope')
    custody = json.loads((SUPPLIED/'official/qwen-gsq-pilot-r6-final-custody.json').read_bytes())
    _, missing = make()
    caller.verify_pilot_reuse(pr,missing,custody)
    for field,value in [('preparer_sha256','0'*64),('recipe_sha256','0'*64),
                        ('shared_client_sha256','0'*64),('whole_client_seconds',419)]:
        changed = copy.deepcopy(pr); changed[field] = value
        with pytest.raises(ValueError): caller.verify_pilot_reuse(changed,missing,custody)


@pytest.mark.parametrize('candidate', ['gsq','ud'])
def test_native_floors_resources_and_effect_helpers_preserved(candidate):
    from test_prepare_qwen_ab import command_resource_contracts
    recipe,r = make(candidate)
    assert r['resource_contracts'] == command_resource_contracts(recipe)
    floors = r['phase_floors_seconds']
    assert floors == dict(identity=60,setup=300,metadata=30,client=420,restore=270,control=80)
    assert r['start_reserve_seconds'] == 300
    assert sum(floors.values()) + r['start_reserve_seconds'] <= r['intent_seconds'] == 1800
    assert 150 + 30 + 420 + 270 <= r['candidate_runtime_seconds'] == 1500
    source = (REF/'LEXICON-MIMO-40-LAST40-R1.remote.py').read_text()
    for func in ('public','observe','guest'):
        assert p.function_bytes(source,func) == p.function_bytes(recipe,func)
    assert 'QWEN_AB_SOL_XHIGH_GATE' in recipe and 'QWEN_AB_ACTUAL_PILOT_RECEIPT_SHA256' in recipe
    assert caller.source_binding(recipe.encode())['source'] == 'ab94e904ca25e2e031ad241f2600aa0406201c15'
