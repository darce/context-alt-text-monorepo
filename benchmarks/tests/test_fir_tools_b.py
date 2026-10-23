"""Synthetic regression reproducers; no corpus images or private mappings."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / 'tools' / 'build_golden_selection.py'

@pytest.fixture
def tool():
    spec = importlib.util.spec_from_file_location('golden_tool', TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def corpus(tmp_path):
    entries = []
    for bucket, count in [('personal', 140), ('celebs', 10)]:
        for i in range(count):
            # 50 identities with spare gallery images, plus 20 anonymous distractors.
            slug = f'person-{i // 3}' if bucket == 'personal' and i < 120 else 'unlabeled'
            if bucket == 'celebs':
                slug = f'celeb-{i}'
            entries.append(dict(path=f'{bucket}/{i}', media_id=len(entries),
                sha256=f'{len(entries):064x}', bucket=bucket, slug=slug,
                primary_identity=None if slug == 'unlabeled' else slug,
                named_face_count=2 if bucket == 'personal' and i < 30 else 1,
                flags=[], width=640, height=480, slice_tags=[], slice_tags_derived=[],
                named_identities=[] if slug == 'unlabeled' else [slug],
                slice_tags_known=False, slice_tags_source=None, detected_face_count=1,
                detected_boxes=[], provenance={'license': 'external' if bucket == 'celebs' else 'consented'}))
    path = tmp_path / 'custom-corpus.json'
    path.write_text(json.dumps(dict(entries=entries, duplicate_groups=[])))
    return path


@pytest.fixture
def corpus150(tmp_path):
    # Fills the default quotas: four images per personal identity leave a gallery spare
    # after the per-identity cap of three; celebs are single-image with external gallery.
    entries = []
    groups = [('personal', 'multi', 7, 4, 2), ('personal', 'core', 34, 4, 1),
              ('personal', None, 20, 1, 0), ('celebs', 'celeb', 10, 1, 1)]
    for bucket, prefix, identities, images, faces in groups:
        for i in range(identities * images):
            slug = f'{prefix}-{i // images}' if prefix else 'unlabeled'
            entries.append(dict(path=f'{bucket}/{len(entries)}', media_id=len(entries),
                sha256=f'{len(entries):064x}', bucket=bucket, slug=slug,
                primary_identity=None if slug == 'unlabeled' else slug,
                named_face_count=faces, flags=[], width=640, height=480, slice_tags=[],
                slice_tags_derived=[], named_identities=[] if slug == 'unlabeled' else [slug],
                slice_tags_known=False, slice_tags_source=None, detected_face_count=1,
                detected_boxes=[], provenance={'license': 'external' if bucket == 'celebs' else 'consented'}))
    path = tmp_path / 'corpus-150.json'
    path.write_text(json.dumps(dict(entries=entries, duplicate_groups=[])))
    return path


def invoke(tool, monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['build_golden_selection', *map(str, args)])
    return tool.main()


def test_defaults_are_checkout_relative(tool, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert tool.MANIFEST_DIR == TOOL.parents[1] / 'manifests'


def test_explicit_output_required(tool, monkeypatch):
    with pytest.raises(SystemExit) as error:
        invoke(tool, monkeypatch, '--verify-only')
    assert error.value.code == 2


@pytest.mark.parametrize('kind', ['existing', 'same-source', 'symlink', 'dangling'])
def test_refuses_existing_destination(tool, monkeypatch, corpus, tmp_path, kind):
    before = corpus.read_bytes()
    out = tmp_path / 'selection.json'
    if kind == 'same-source':
        out = corpus
    elif kind in ('symlink', 'dangling'):
        out.symlink_to(corpus if kind == 'symlink' else tmp_path / 'missing')
    else:
        out.write_text('sentinel')
    assert invoke(tool, monkeypatch, '--corpus', corpus, '--out', out) != 0
    assert corpus.read_bytes() == before
    if kind == 'existing':
        assert out.read_text() == 'sentinel'
    if kind in ('symlink', 'dangling'):
        assert out.is_symlink()


def test_invalid_selection_not_published(tool, monkeypatch, corpus, tmp_path):
    out = tmp_path / 'invalid.json'
    before = corpus.read_bytes()
    assert invoke(tool, monkeypatch, '--corpus', corpus, '--out', out) != 0
    assert not out.exists()
    assert corpus.read_bytes() == before


def test_malformed_input_not_published(tool, monkeypatch, tmp_path):
    source = tmp_path / 'bad.json'
    source.write_text('{')
    out = tmp_path / 'out.json'
    assert invoke(tool, monkeypatch, '--corpus', source, '--out', out) != 0
    assert not out.exists()


def test_custom_input_and_readonly_verification(tool, monkeypatch, corpus, tmp_path):
    # Use small quotas to exercise real build/verify with this synthetic corpus.
    monkeypatch.setattr(tool, 'QUOTAS', dict(recognition_core=30, multi_face=20, distractor=20, celeb=10))
    monkeypatch.setattr(tool, 'SIZE', 80)
    before = corpus.read_bytes()
    out = tmp_path / 'new.json'
    monkeypatch.chdir(tmp_path)
    assert invoke(tool, monkeypatch, '--corpus', corpus, '--out', out) == 0
    selection = json.loads(out.read_text())
    assert selection['corpus_manifest'] == corpus.name
    assert selection['corpus_manifest_sha256'] == hashlib.sha256(before).hexdigest()
    content = out.read_bytes()
    out.chmod(0o444)
    assert invoke(tool, monkeypatch, '--corpus', corpus, '--out', out, '--verify-only') == 0
    assert out.read_bytes() == content
    assert corpus.read_bytes() == before


def build150(tool, monkeypatch, corpus, tmp_path):
    out = tmp_path / 'golden150.json'
    assert invoke(tool, monkeypatch, '--corpus', corpus, '--out', out) == 0
    selection = json.loads(out.read_text())
    assert selection['size'] == 150
    assert selection['realized']['by_stratum'] == tool.QUOTAS
    out.chmod(0o444)
    return out, selection


@pytest.mark.parametrize('edit', ['hand-tags', 'reserialized'])
def test_verify_rejects_corpus_bytes_off_the_pin(tool, monkeypatch, capsys, corpus150, tmp_path, edit):
    out, selection = build150(tool, monkeypatch, corpus150, tmp_path)
    content = out.read_bytes()
    assert invoke(tool, monkeypatch, '--corpus', corpus150, '--out', out, '--verify-only') == 0
    doc = json.loads(corpus150.read_bytes())
    if edit == 'hand-tags':
        # IDs, paths and sha256 all still agree; only the operator's tags moved.
        picked = selection['selection'][0]['path']
        next(e for e in doc['entries'] if e['path'] == picked)['slice_tags'] = ['sunglasses']
        stale = json.dumps(doc).encode()
    else:
        stale = json.dumps(doc, indent=1).encode()
    corpus150.write_bytes(stale)
    capsys.readouterr()
    assert invoke(tool, monkeypatch, '--corpus', corpus150, '--out', out, '--verify-only') != 0
    assert 'corpus_manifest_sha256 pin' in capsys.readouterr().err
    assert out.read_bytes() == content
    assert corpus150.read_bytes() == stale


@pytest.mark.parametrize('pin', ['missing', None, 'upper', 'other'])
def test_verify_rejects_missing_or_wrong_pin(tool, monkeypatch, corpus150, tmp_path, pin):
    _, selection = build150(tool, monkeypatch, corpus150, tmp_path)
    digest = selection['corpus_manifest_sha256']
    if pin == 'missing':
        del selection['corpus_manifest_sha256']
    else:
        selection['corpus_manifest_sha256'] = dict(
            upper=digest.upper(), other=hashlib.sha256(b'').hexdigest()).get(pin)
    out = tmp_path / 'repinned.json'
    out.write_text(json.dumps(selection))
    assert invoke(tool, monkeypatch, '--corpus', corpus150, '--out', out, '--verify-only') != 0


def test_verify_hashes_the_bytes_it_parsed(tool, monkeypatch, capsys, corpus150, tmp_path):
    out, _ = build150(tool, monkeypatch, corpus150, tmp_path)
    pinned = corpus150.read_bytes()
    doc = json.loads(pinned)
    doc['entries'][0]['slice_tags'] = ['blur']
    corpus150.write_text(json.dumps(doc))
    read_bytes = Path.read_bytes

    def read_then_restore(self):
        data = read_bytes(self)
        if self == corpus150:
            # A concurrent writer puts the pinned bytes back right after the read, so a
            # second read for hashing would vouch for content that was never checked.
            corpus150.write_bytes(pinned)
        return data

    monkeypatch.setattr(Path, 'read_bytes', read_then_restore)
    capsys.readouterr()
    assert invoke(tool, monkeypatch, '--corpus', corpus150, '--out', out, '--verify-only') != 0
    assert 'corpus_manifest_sha256 pin' in capsys.readouterr().err
