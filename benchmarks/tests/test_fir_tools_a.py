"""Regression tests for explicit, portable, no-clobber manifest publication."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'tools/build_corpus_manifest.py'

@pytest.fixture
def tool():
    spec = importlib.util.spec_from_file_location('builder', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def invoke(tool, monkeypatch, *args):
    monkeypatch.setattr(sys, 'argv', ['builder', *map(str, args)])
    return tool.main()

@pytest.mark.parametrize('extra', [[], ['--verify-only']])
def test_explicit_output_required(tool, monkeypatch, extra):
    monkeypatch.setattr(tool, 'build', lambda **kw: pytest.fail('must reject before build'))
    with pytest.raises(SystemExit) as exc:
        invoke(tool, monkeypatch, *extra)
    assert exc.value.code == 2

@pytest.mark.parametrize('kind', ['file', 'symlink', 'dangling', 'directory'])
def test_existing_destination_unchanged(tool, monkeypatch, tmp_path, kind):
    target = tmp_path / 'source.json'
    target.write_text('sentinel')
    out = tmp_path / 'out.json'
    if kind == 'file':
        out.write_text('sentinel')
    elif kind == 'directory':
        out.mkdir()
    else:
        out.symlink_to(target if kind == 'symlink' else tmp_path / 'missing')
    monkeypatch.setattr(tool, 'build', lambda **kw: pytest.fail('must refuse before build'))
    assert invoke(tool, monkeypatch, '--out', out) == 1
    assert target.read_text() == 'sentinel'
    if kind == 'file':
        assert out.read_text() == 'sentinel'

@pytest.mark.parametrize('valid', [False, True])
def test_validation_before_publication(tool, monkeypatch, tmp_path, valid):
    source = tmp_path / 'source.json'
    source.write_text('unchanged')
    out = tmp_path / 'out.json'
    manifest = {'counts': {'flags': {}}}
    monkeypatch.setattr(tool, 'build', lambda **kw: manifest)
    monkeypatch.setattr(tool, 'verify', lambda *a, **kw: [] if valid else ['bad manifest'])
    assert invoke(tool, monkeypatch, '--out', out, '--corpus', source) == (0 if valid else 1)
    assert out.exists() == valid
    assert source.read_text() == 'unchanged'
    if valid:
        assert json.loads(out.read_text()) == manifest

def test_verify_only_never_builds_or_writes(tool, monkeypatch, tmp_path):
    out = tmp_path / 'manifest.json'
    original = '{"counts": {"flags": {}}}'
    out.write_text(original)
    monkeypatch.setattr(tool, 'build', lambda **kw: pytest.fail('verification built images'))
    monkeypatch.setattr(tool, 'verify', lambda *a, **kw: [])
    assert invoke(tool, monkeypatch, '--verify-only', '--out', out) == 0
    assert out.read_text() == original

def test_defaults_are_checkout_relative(tool, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert tool.CORPUS646 == SOURCE.parents[1] / 'manifests/corpus646-interleave-manifest-20260716.json'

def test_malformed_input_leaves_no_output(tool, monkeypatch, tmp_path):
    source = tmp_path / 'bad.json'
    source.write_text('{')
    out = tmp_path / 'out.json'
    assert invoke(tool, monkeypatch, '--out', out, '--corpus', source) == 1
    assert not out.exists()
    assert source.read_text() == '{'

def test_build_overrides_preserve_sha_spaces(tool, monkeypatch, tmp_path):
    import hashlib
    import types
    root = tmp_path / 'images'
    for bucket in tool.BUCKETS:
        (root / bucket).mkdir(parents=True)
    image = root / 'personal/person_1.png'
    image.write_bytes(b'synthetic image fixture')
    class ImageContext:
        size = (12, 9)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setitem(sys.modules, 'PIL', types.SimpleNamespace(
        Image=types.SimpleNamespace(open=lambda path: ImageContext())))
    corpus = tmp_path / 'corpus.json'
    golden = tmp_path / 'golden.json'
    detections = tmp_path / 'detections.json'
    corpus.write_text(json.dumps({'entries': [{'media_id': 1, 'path': 'personal/person_1.png', 'sha256': 'original-sha'}]}))
    golden.write_text('{"entries": []}')
    detections.write_text('{"entries": [], "detector": {}}')
    originals = [p.read_bytes() for p in (corpus, golden, detections)]
    monkeypatch.chdir(tmp_path)
    out = tmp_path / 'new.json'
    assert invoke(tool, monkeypatch, '--out', out, '--corpus', corpus,
                  '--golden', golden, '--detections', detections, '--images-root', root) == 0
    manifest = json.loads(out.read_text())
    entry = manifest['entries'][0]
    assert (entry['width'], entry['height']) == (12, 9)
    assert entry['sha256'] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert entry['sha256_source'] == 'original-sha'
    assert (manifest['sha256_space'], manifest['sha256_source_space']) == ('downscaled', 'original')
    assert [p.read_bytes() for p in (corpus, golden, detections)] == originals
    before = out.read_bytes()
    assert invoke(tool, monkeypatch, '--out', out, '--verify-only', '--images-root', root) == 0
    assert out.read_bytes() == before


def test_serialization_failure_does_not_create_output(tool, monkeypatch, tmp_path):
    monkeypatch.setattr(tool, 'build', lambda **kw: {'invalid': float('nan')})
    monkeypatch.setattr(tool, 'verify', lambda *a, **kw: [])
    out = tmp_path / 'out.json'
    assert invoke(tool, monkeypatch, '--out', out) == 1
    assert not out.exists()


def test_destination_created_during_build_is_preserved(tool, monkeypatch, tmp_path):
    out = tmp_path / 'out.json'
    def build(**kwargs):
        out.write_text('competing writer evidence')
        return {'counts': {'flags': {}}}
    monkeypatch.setattr(tool, 'build', build)
    monkeypatch.setattr(tool, 'verify', lambda *a, **kw: [])
    assert invoke(tool, monkeypatch, '--out', out) == 1
    assert out.read_text() == 'competing writer evidence'
