"""Runner checks for replacement-038: the record must agree with the recipe, and --pilot is required. No VM, ssh or recipe execution."""
import importlib.util
import json
from pathlib import Path
from unittest import mock

import pytest

QWEN_AB = Path(__file__).resolve().parent
REF = QWEN_AB / 'references'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUN = load('run_qwen_cohort_operation', QWEN_AB / 'run_qwen_cohort_operation.py')
P = load('prepare_qwen_ab_for_runner_tests', QWEN_AB / 'workspace' / 'prepare_qwen_ab.py')
OLD_038 = '648573b4d21c3e1b7d8029246ed20f5a516f685f6c698af2249109183cf524bd'
NEW_038 = '710a6798653ef868338136da63e2c176e892d73bac342e395bf0df640e70022e'


def revision_record():
    return {'schema': 'bakeoff-corpus-revision/v1', 'revision': 'r2', 'image_id': 'original-038',
            'previous': {'image_id': 'original-038', 'path': 'corpus-original/original-038.jpg', 'sha256': OLD_038},
            'replacement': {'image_id': 'original-038', 'path': 'corpus-revisions/r2/original-038.jpg',
                            'sha256': NEW_038, 'context_pack': {}, 'present_identities': [],
                            'dataset_revision': 'r2', 'replaces_sha256': OLD_038},
            'old_outputs_reused_for_replacement': False,
            'required_GPU_models': ['mimo', 'qwen-gsq', 'joy', 'incumbent']}


@pytest.fixture
def replacement(tmp_path):
    """A replacement recipe and its receipt, prepared from a fixture revision whose digest is pinned to the fixture."""
    raw = (json.dumps(revision_record(), indent=2) + '\n').encode()
    path = tmp_path / 'corpus-revision-r2.json'
    path.write_bytes(raw)
    with mock.patch.object(P, 'R2_REVISION_SHA256', P.sha(raw)):
        recipe, receipt = P.prepare(REF, 'gsq', 'replacement', 'QWEN-R2-038', 'workbay-qwen-r2-038.scope', revision=path)
    return recipe.encode(), json.loads(json.dumps(receipt))


def test_replacement_record_verifies_against_its_recipe(replacement):
    raw, receipt = replacement
    assert RUN.verify_prepared(receipt, raw).startswith('/tmp/qwen-owner-window.')
    assert RUN.source_binding(raw)['workspace'].endswith('/workspace')


@pytest.mark.parametrize('edit, message', [
    (lambda r: r['replacement'].update(new_sha256='2' * 64), 'disagrees'),
    (lambda r: r['replacement'].update(path='/tmp/elsewhere.jpg'), 'disagrees'),
    (lambda r: r['replacement'].update(revision_sha256='3' * 64), 'revision pin'),
    (lambda r: r['replacement'].update(image_id='original-039'), 'name original-038'),
    (lambda r: r.pop('replacement'), 'name original-038'),
    (lambda r: r.update(total_distinct_images=20), 'one image'),
    (lambda r: r.update(completion_POST_budget=60), 'one image'),
])
def test_replacement_record_must_match_the_embedded_image(replacement, edit, message):
    raw, receipt = replacement
    edit(receipt)
    with pytest.raises(ValueError, match=message):
        RUN.verify_prepared(receipt, raw)


def test_replacement_record_is_valid_only_in_replacement_mode(replacement):
    raw, receipt = replacement
    receipt['mode'] = 'full'
    with pytest.raises(ValueError, match='only in replacement mode'):
        RUN.verify_prepared(receipt, raw)


@pytest.mark.parametrize('mode, pilot, accepted', [
    ('pilot', None, True), ('pilot', 'p', False),
    ('full', None, False), ('full', 'p', True),
    ('replacement', None, False), ('replacement', 'p', True),
])
def test_pilot_is_required_iff_full_or_replacement(mode, pilot, accepted):
    prepared = dict(mode=mode)
    if accepted:
        RUN.pilot_requirement(prepared, pilot)
    else:
        with pytest.raises(ValueError, match='iff the prepared mode is full or replacement'):
            RUN.pilot_requirement(prepared, pilot)
