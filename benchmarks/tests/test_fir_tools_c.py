"""Portable CLI and no-clobber regression tests; no model or image fixtures."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'


def cli(tool, *args, cwd=None):
    return subprocess.run([sys.executable, str(TOOLS / (tool + '.py')), *map(str, args)],
                          cwd=cwd, capture_output=True, text=True)


@pytest.mark.parametrize('tool', ['pose_features', 'calibrate_slice_tags', 'run_detection_pass'])
def test_help_and_required_output(tool, tmp_path):
    assert cli(tool, '--help', cwd=tmp_path).returncode == 0
    assert cli(tool, cwd=tmp_path).returncode != 0


@pytest.mark.parametrize('tool', ['pose_features', 'calibrate_slice_tags', 'run_detection_pass'])
@pytest.mark.parametrize('symlink', [False, True])
def test_existing_output_untouched(tool, symlink, tmp_path):
    sentinel = tmp_path / 'sentinel'
    sentinel.write_text('evidence')
    out = tmp_path / 'out'
    if symlink:
        out.symlink_to(sentinel)
    else:
        out.write_text('evidence')
    args = [tmp_path / 'missing'] if tool == 'pose_features' else []
    result = cli(tool, *args, '--out', out)
    assert result.returncode != 0
    assert 'choose a new output' in result.stderr.lower()
    assert sentinel.read_text() == 'evidence'
    assert out.read_text() == 'evidence'


def test_pose_separate_output_and_invalid_landmarks(tmp_path):
    src, out = tmp_path / 'source.json', tmp_path / 'out.json'
    data = {'entries': [{'faces': [{'landmarks': [[0, 0], [2, 0], [1, 1], [0, 2], [2, 2]]}]}]}
    original = json.dumps(data)
    src.write_text(original)
    assert cli('pose_features', src, '--out', src).returncode != 0
    assert src.read_text() == original
    assert cli('pose_features', src, '--out', out).returncode == 0
    assert src.read_text() == original
    assert json.loads(out.read_text())['entries'][0]['faces'][0]['yaw_eye'] == 0
    for landmarks in ([[1, 2]], [[float('nan'), 0]] * 5):
        data['entries'][0]['faces'][0]['landmarks'] = landmarks
        src.write_text(json.dumps(data))
        invalid_out = tmp_path / 'invalid.json'
        assert cli('pose_features', src, '--out', invalid_out).returncode != 0
        assert not invalid_out.exists()


def test_calibration_toy(tmp_path):
    paths = [tmp_path / name for name in ('det', 'gold', 'corpus')]
    for path in paths:
        path.write_text('{"entries": []}')
    out = tmp_path / 'result'
    result = cli('calibrate_slice_tags', '--detections', paths[0], '--golden', paths[1],
                 '--corpus', paths[2], '--out', out, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text()) == {'auc_floor': .75, 'labelled_images': 0,
                                         'shippable': {}, 'named_but_undetected': []}


@pytest.mark.parametrize('tool,flag', [('pose_features', None), ('calibrate_slice_tags', '--detections'),
                                       ('run_detection_pass', '--corpus')])
def test_malformed_no_output(tool, flag, tmp_path):
    src, out = tmp_path / 'bad', tmp_path / 'out'
    src.write_text('{')
    args = [flag, src] if flag else [src]
    assert cli(tool, *args, '--out', out).returncode != 0
    assert not out.exists()


@pytest.mark.parametrize('tool', ['pose_features', 'calibrate_slice_tags', 'run_detection_pass'])
def test_import_and_help_without_inference_dependencies(tool, tmp_path):
    script = """
import importlib.util
import sys
class Block:
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'numpy', 'cv2', 'recognition'}:
            raise ImportError(fullname)
sys.meta_path.insert(0, Block())
spec = importlib.util.spec_from_file_location('tool', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
if hasattr(module, 'MANIFEST_DIR'):
    from pathlib import Path
    assert module.MANIFEST_DIR == Path(sys.argv[1]).resolve().parents[1] / 'manifests'
module.main(['--help'])
"""
    result = subprocess.run([sys.executable, '-c', script, str(TOOLS / (tool + '.py'))],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_pose_dangling_symlink_output(tmp_path):
    out = tmp_path / 'out'
    target = tmp_path / 'absent'
    out.symlink_to(target)
    result = cli('pose_features', tmp_path / 'missing', '--out', out)
    assert 'choose a new output' in result.stderr.lower()
    assert out.is_symlink()
    assert not target.exists()
