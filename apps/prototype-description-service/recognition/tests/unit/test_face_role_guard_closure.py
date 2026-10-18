"""Discriminating offline controls for C82R-HFACEG2-F8 guard deletions."""
from __future__ import annotations

import pytest

from recognition.tests.unit import test_face_role_attestation_publisher as pub
from recognition.tests.unit.test_face_role_attestation_publisher import isolated_import_state as isolated_import_state


@pytest.mark.parametrize('version', [True, 1.0])
def test_baked_writer_refuses_noninteger_version(tmp_path, monkeypatch, version):
    source = pub.source_producer()
    pub.clear_source_environment(monkeypatch)
    fields = pub.identity_args()
    fields.pop('identity_document_sha256')
    valid = tmp_path / 'valid.json'
    assert source.write_baked_source_identity(valid, **fields).source_identity_version == 1
    fields['source_identity_version'] = version
    rejected = tmp_path / 'rejected.json'
    with pytest.raises(ValueError, match='incompatible_version'):
        source.write_baked_source_identity(rejected, **fields)
    assert not rejected.exists()


@pytest.mark.parametrize('version', [0, 2])
def test_baked_writer_refuses_unsupported_integer_version(tmp_path, monkeypatch, version):
    source = pub.source_producer()
    pub.clear_source_environment(monkeypatch)
    fields = pub.identity_args()
    fields.pop('identity_document_sha256')
    assert source.write_baked_source_identity(tmp_path / 'valid.json', **fields).source_identity_version == 1
    fields['source_identity_version'] = version
    rejected = tmp_path / 'rejected.json'
    with pytest.raises(ValueError, match='incompatible_version'):
        source.write_baked_source_identity(rejected, **fields)
    assert not rejected.exists()


def test_allowlisted_value_still_refuses_mail_shape():
    module = pub.producer()
    options = pub.inputs()
    assert module.build_face_role_record(**options).effective_settings['profile'] == 'auraface'
    options['effective_settings']['profile'] = 'fixture' + chr(64) + 'invalid.example'
    with pytest.raises(ValueError, match='unsafe_record_string'):
        module.build_face_role_record(**options)


def test_repair_absent_image_is_valid_incomplete():
    module = pub.producer()
    options = pub.repair_inputs()
    assert module.RepairIdentityRecordV1(**options).collection_status == 'complete'
    options.update(image_record=None, source_identity=None, collection_status='incomplete')
    record = module.RepairIdentityRecordV1(**options)
    assert record.image_record is None and record.source_identity is None
    assert record.collection_status == 'incomplete'


@pytest.mark.parametrize('value', [1, True, ['fixture'], {'fixture': 'value'}])
def test_repair_refuses_nonstring_image_value(value):
    module = pub.producer()
    options = pub.repair_inputs()
    options['image_record']['container_id'] = 'fixture'
    assert module.RepairIdentityRecordV1(**options).image_record['container_id'] == 'fixture'
    options['image_record']['container_id'] = value
    with pytest.raises(ValueError, match='invalid_image_value'):
        module.RepairIdentityRecordV1(**options)


@pytest.mark.parametrize('field', ['registry_manifest_digest', 'image_config_digest'])
def test_repair_absent_image_digest_is_valid_incomplete(field):
    module = pub.producer()
    options = pub.repair_inputs()
    assert module.RepairIdentityRecordV1(**options).collection_status == 'complete'
    options['collection_status'] = 'incomplete'
    del options['image_record'][field]
    record = module.RepairIdentityRecordV1(**options)
    assert record.collection_status == 'incomplete'
    assert field not in record.image_record


def test_repair_absent_document_digest_is_valid_incomplete():
    module = pub.producer()
    options = pub.repair_inputs()
    assert module.RepairIdentityRecordV1(**options).collection_status == 'complete'
    options['collection_status'] = 'incomplete'
    del options['image_record']['identity_document_sha256']
    record = module.RepairIdentityRecordV1(**options)
    assert record.collection_status == 'incomplete'
    assert 'identity_document_sha256' not in record.image_record


def test_repair_absent_source_is_valid_incomplete():
    module = pub.producer()
    options = pub.repair_inputs()
    assert module.RepairIdentityRecordV1(**options).collection_status == 'complete'
    options.update(source_identity=None, collection_status='incomplete')
    record = module.RepairIdentityRecordV1(**options)
    assert record.collection_status == 'incomplete' and record.source_identity is None


def test_attestation_refuses_sequence_with_correct_session_names():
    module = pub.producer()
    row = pub.plain(pub.attested_observation('worker'))
    assert module._attested(row) is True
    row['runtime_record']['sessions'] = ['yunet', 'auraface']
    assert module._attested(row) is False


def test_settings_allowlist_refuses_benign_unknown_field():
    module = pub.producer()
    options = pub.inputs()
    assert module.build_face_role_record(**options).effective_settings == options['effective_settings']
    options['effective_settings']['unlisted_fixture_setting'] = 'fixture'
    with pytest.raises(ValueError, match='unallowlisted_settings'):
        module.build_face_role_record(**options)


@pytest.mark.parametrize('absent', [True, False])
def test_absent_runtime_is_valid_incomplete(absent):
    module = pub.producer()
    options = pub.complete_inputs()
    assert module.build_face_role_record(**options).collection_status == 'complete'
    row = options['adapter_observations'][0]
    if absent:
        del row['runtime_record']
    else:
        row['runtime_record'] = None
    record = module.build_face_role_record(**options)
    assert record.collection_status == 'incomplete'
    assert record.reason_code == 'evidence_incomplete'
    assert record.adapter_observations[0].get('runtime_record') is None


def test_supported_unexercised_runtime_keeps_evidence_incomplete_reason():
    module = pub.producer()
    options = pub.complete_inputs()
    assert module.build_face_role_record(**options).collection_status == 'complete'
    options['adapter_observations'] = (pub.observation('fixture-generation', 'fixture-adapter'),)
    record = module.build_face_role_record(**options)
    assert record.collection_status == 'incomplete'
    assert record.reason_code == 'evidence_incomplete'


@pytest.mark.parametrize('runtime', [[], 1, True, 'fixture'])
def test_nonmapping_runtime_is_refused(runtime):
    module = pub.producer()
    options = pub.complete_inputs()
    assert module.build_face_role_record(**options).collection_status == 'complete'
    options['adapter_observations'][0]['runtime_record'] = runtime
    with pytest.raises(ValueError, match='incompatible_version'):
        module.build_face_role_record(**options)


def test_baked_writer_refuses_symlink_installed_during_validation(tmp_path, monkeypatch):
    source = pub.source_producer()
    pub.clear_source_environment(monkeypatch)
    fields = pub.identity_args()
    fields.pop('identity_document_sha256')
    target = tmp_path / 'identity.json'
    victim = tmp_path / 'victim.json'
    victim.write_bytes(b'fixture-victim')
    original_load = source.load_baked_source_identity
    swaps = []

    def load_then_swap(path, **kwargs):
        identity = original_load(path, **kwargs)
        assert not target.exists()
        target.symlink_to(victim)
        swaps.append(path)
        return identity

    with monkeypatch.context() as patch:
        patch.setattr(source, 'load_baked_source_identity', load_then_swap)
        with pytest.raises(ValueError, match='invalid_identity_file'):
            source.write_baked_source_identity(target, **fields)
    assert len(swaps) == 1
    assert target.is_symlink() and target.resolve() == victim
    assert victim.read_bytes() == b'fixture-victim'
    assert sorted(path.name for path in tmp_path.iterdir()) == ['identity.json', 'victim.json']


def test_baked_writer_refuses_symlink_before_it_can_disappear(tmp_path, monkeypatch):
    source = pub.source_producer()
    pub.clear_source_environment(monkeypatch)
    fields = pub.identity_args()
    fields.pop('identity_document_sha256')
    target = tmp_path / 'identity.json'
    victim = tmp_path / 'victim.json'
    victim.write_bytes(b'fixture-victim')
    target.symlink_to(victim)
    original_load = source.load_baked_source_identity
    swaps = []

    def load_then_unlink(path, **kwargs):
        identity = original_load(path, **kwargs)
        target.unlink()
        swaps.append(path)
        return identity

    with monkeypatch.context() as patch:
        patch.setattr(source, 'load_baked_source_identity', load_then_unlink)
        with pytest.raises(ValueError, match='invalid_identity_file'):
            source.write_baked_source_identity(target, **fields)
    assert swaps == []
    assert target.is_symlink() and target.resolve() == victim
    assert victim.read_bytes() == b'fixture-victim'
    assert sorted(path.name for path in tmp_path.iterdir()) == ['identity.json', 'victim.json']
