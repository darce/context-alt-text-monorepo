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
