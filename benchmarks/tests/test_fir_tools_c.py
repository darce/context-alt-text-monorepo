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


# Detection-pass face row after pose enrichment; every calibration signal is usable.
FACE = {'bbox': [10.0, 10.0, 80.0, 100.0],
        'landmarks': [[30.0, 40.0], [60.0, 40.0], [45.0, 60.0], [33.0, 80.0], [57.0, 80.0]],
        'face_min_side': 80.0, 'face_area_frac': 0.08, 'interocular_ratio': 0.375, 'nose_offset': 0.0,
        'blur_var': 100.0, 'score': 0.95, 'yaw_eye': 0.0, 'yaw_mouth': 0.0, 'eye_span_ratio': 0.75,
        'roll_deg': 0.0}
NO_SIGNALS = {k: None for k in FACE if k not in ('bbox', 'landmarks')}
BLUR_SHIPS = {'signal': 'blur_var', 'direction': -1, 'threshold': 10.0, 'auc': 1.0,
              'f1': 1.0, 'precision': 1.0, 'recall': 1.0}


def calibrate(tmp_path, images):
    """Run calibration on synthetic (tags, face) rows; assert inputs are left unchanged."""
    docs = {
        'det': {'entries': [{'media_id': i, 'path': f'synthetic/{i}.jpg', 'sha256': '0' * 64,
                             'width': 100, 'height': 100, 'faces': [face]}
                            for i, (_, face) in enumerate(images)]},
        'gold': {'entries': [{'media_id': i, 'tags': tags} for i, (tags, _) in enumerate(images)]},
        'corpus': {'entries': [{'media_id': i, 'named_boxes': []} for i in range(len(images))]},
    }
    for name, doc in docs.items():
        (tmp_path / name).write_text(json.dumps(doc))
    out = tmp_path / 'result'
    result = cli('calibrate_slice_tags', '--detections', tmp_path / 'det', '--golden', tmp_path / 'gold',
                 '--corpus', tmp_path / 'corpus', '--out', out, cwd=tmp_path)
    for name, doc in docs.items():
        assert json.loads((tmp_path / name).read_text()) == doc
    assert result.returncode == 0, result.stderr
    rows = {line.split()[0]: line for line in result.stdout.splitlines() if line.strip()}
    return json.loads(out.read_text()), rows


def test_calibration_single_one_class_image(tmp_path):
    published, rows = calibrate(tmp_path, [(['profile'], FACE)])
    assert published == {'auc_floor': .75, 'labelled_images': 1, 'shippable': {},
                         'named_but_undetected': []}
    assert 'insufficient' in rows['profile'] and 'nan' not in rows['profile']


@pytest.mark.parametrize('images', [
    # One class: every detected image carries `profile`, so no signal has a negative.
    [(['profile', 'blur'], {**FACE, 'blur_var': 10.0}), (['profile'], FACE)],
    # No usable signal: `profile` has both classes but never on the same signal.
    [(['profile'], {**FACE, **NO_SIGNALS, 'nose_offset': 0.4}),
     ([], {**FACE, **NO_SIGNALS, 'blur_var': 100.0}),
     (['blur'], {**FACE, **NO_SIGNALS, 'blur_var': 10.0})],
], ids=['one_class', 'no_usable_signal'])
def test_calibration_skips_undiscriminable_tag_and_continues(images, tmp_path):
    published, rows = calibrate(tmp_path, images)
    assert published == {'auc_floor': .75, 'labelled_images': len(images), 'shippable': {'blur': BLUR_SHIPS},
                         'named_but_undetected': []}
    assert 'insufficient' in rows['profile'] and 'nan' not in rows['profile']
    assert rows['blur'].endswith('SHIP')


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
