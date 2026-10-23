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
                                         'shippable': {}, 'named_but_undetected': [],
                                         'unqualified_tags': {
                                             tag: {'reason': 'no_positive_examples',
                                                   'positive_count': 0, 'negative_count': 0}
                                             for tag in CALIBRATION_TAGS}}


# Detection-pass face row after pose enrichment; every calibration signal is usable.
FACE = {'bbox': [10.0, 10.0, 80.0, 100.0],
        'landmarks': [[30.0, 40.0], [60.0, 40.0], [45.0, 60.0], [33.0, 80.0], [57.0, 80.0]],
        'face_min_side': 80.0, 'face_area_frac': 0.08, 'interocular_ratio': 0.375, 'nose_offset': 0.0,
        'blur_var': 100.0, 'score': 0.95, 'yaw_eye': 0.0, 'yaw_mouth': 0.0, 'eye_span_ratio': 0.75,
        'roll_deg': 0.0}
NO_SIGNALS = {k: None for k in FACE if k not in ('bbox', 'landmarks')}
BLUR_SHIPS = {'signal': 'blur_var', 'direction': -1, 'threshold': 10.0, 'auc': 1.0,
              'f1': 1.0, 'precision': 1.0, 'recall': 1.0}
CALIBRATION_TAGS = {'profile', 'blur', 'low_res', 'sunglasses', 'masked', 'occlusion_other'}


def calibrate(tmp_path, images):
    """Run calibration on synthetic (tags, face) rows; assert inputs are left unchanged."""
    docs = {
        'det': {'entries': [{'media_id': i, 'path': f'synthetic/{i}.jpg', 'sha256': '0' * 64,
                             'width': 100, 'height': 100, 'faces': [face] if face is not None else []}
                            for i, (_, face) in enumerate(images)]},
        'gold': {'entries': [{'media_id': i, **({'tags': tags} if tags is not None else {})}
                             for i, (tags, _) in enumerate(images)]},
        'corpus': {'entries': [{'media_id': i, 'named_boxes': []} for i in range(len(images))]},
    }
    originals = {name: json.dumps(doc) for name, doc in docs.items()}
    for name, original in originals.items():
        (tmp_path / name).write_text(original)
    out = tmp_path / 'result'
    result = cli('calibrate_slice_tags', '--detections', tmp_path / 'det', '--golden', tmp_path / 'gold',
                 '--corpus', tmp_path / 'corpus', '--out', out, cwd=tmp_path)
    for name, original in originals.items():
        assert (tmp_path / name).read_text() == original
    assert result.returncode == 0, result.stderr
    saved = out.read_text()
    published = json.loads(saved)
    json.dumps(published, allow_nan=False)
    assert published['shippable'].keys().isdisjoint(published['unqualified_tags'])
    assert published['shippable'].keys() | published['unqualified_tags'].keys() == CALIBRATION_TAGS
    repeated = cli('calibrate_slice_tags', '--detections', tmp_path / 'det', '--golden', tmp_path / 'gold',
                   '--corpus', tmp_path / 'corpus', '--out', out, cwd=tmp_path)
    assert repeated.returncode != 0
    assert 'choose a new output' in repeated.stderr.lower()
    assert out.read_text() == saved
    rows = {line.split()[0]: line for line in result.stdout.splitlines() if line.strip()}
    return published, rows


def test_calibration_single_one_class_image(tmp_path):
    published, rows = calibrate(tmp_path, [(['profile'], FACE)])
    assert published == {'auc_floor': .75, 'labelled_images': 1, 'shippable': {},
                         'named_but_undetected': [],
                         'unqualified_tags': {
                             'profile': {'reason': 'insufficient_data', 'positive_count': 1, 'negative_count': 0},
                             **{tag: {'reason': 'no_positive_examples', 'positive_count': 0, 'negative_count': 1}
                                for tag in CALIBRATION_TAGS - {'profile'}}}}
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
                         'named_but_undetected': [],
                         'unqualified_tags': {
                             'profile': {'reason': 'insufficient_data',
                                         'positive_count': 2 if len(images) == 2 else 1,
                                         'negative_count': 0 if len(images) == 2 else 2},
                             **{tag: {'reason': 'no_positive_examples',
                                      'positive_count': 0, 'negative_count': len(images)}
                                for tag in CALIBRATION_TAGS - {'profile', 'blur'}}}}
    assert 'insufficient' in rows['profile'] and 'nan' not in rows['profile']
    assert rows['blur'].endswith('SHIP')


def test_calibration_persists_below_floor_and_no_positive_reasons(tmp_path):
    published, rows = calibrate(tmp_path, [(['profile'], FACE), ([], FACE),
                                         (['profile', 'blur'], {**FACE, 'blur_var': 10.0}),
                                         (['blur'], {**FACE, 'blur_var': 10.0})])
    assert published == {'auc_floor': .75, 'labelled_images': 4, 'named_but_undetected': [],
                         'shippable': {'blur': BLUR_SHIPS},
                         'unqualified_tags': {
                             'profile': {'reason': 'below_auc_floor', 'positive_count': 2,
                                         'negative_count': 2, 'auc': .5},
                             **{tag: {'reason': 'no_positive_examples', 'positive_count': 0, 'negative_count': 4}
                                for tag in CALIBRATION_TAGS - {'profile', 'blur'}}}}
    assert rows['profile'].endswith('noise - hand-tag only')
    assert rows['blur'].endswith('SHIP')


def test_calibration_qualifies_at_auc_floor(tmp_path):
    published, _ = calibrate(tmp_path, [([], FACE), (['blur'], FACE),
                                      (['blur'], {**FACE, 'blur_var': 10.0})])
    assert published['shippable'] == {'blur': {'signal': 'blur_var', 'direction': -1, 'threshold': 100.0,
                                            'auc': .75, 'f1': .8, 'precision': .667, 'recall': 1.0}}
    assert published['unqualified_tags'] == {
        tag: {'reason': 'no_positive_examples', 'positive_count': 0, 'negative_count': 3}
        for tag in CALIBRATION_TAGS - {'blur'}}


def test_calibration_without_any_signals(tmp_path):
    published, _ = calibrate(tmp_path, [(['profile'], {**FACE, **NO_SIGNALS}),
                                      ([], {**FACE, **NO_SIGNALS})])
    assert published == {'auc_floor': .75, 'labelled_images': 2, 'shippable': {},
                         'named_but_undetected': [],
                         'unqualified_tags': {
                             'profile': {'reason': 'insufficient_data', 'positive_count': 1, 'negative_count': 1},
                             **{tag: {'reason': 'no_positive_examples', 'positive_count': 0, 'negative_count': 2}
                                for tag in CALIBRATION_TAGS - {'profile'}}}}


def test_calibration_all_tags_qualify(tmp_path):
    published, _ = calibrate(tmp_path, [(sorted(CALIBRATION_TAGS), {**FACE, 'blur_var': 10.0}), ([], FACE)])
    assert published == {'auc_floor': .75, 'labelled_images': 2,
                         'shippable': {tag: BLUR_SHIPS for tag in CALIBRATION_TAGS},
                         'unqualified_tags': {}, 'named_but_undetected': []}


def test_calibration_counts_only_detected_labelled_images(tmp_path):
    # A missed positive face is outside the existing calibration frame. Unknown tags
    # do not expand the known-tag vocabulary; an empty tags list is a true negative.
    published, _ = calibrate(tmp_path, [(['profile'], None), (None, FACE),
                                      (['operator_note'], FACE), ([], FACE)])
    assert published == {'auc_floor': .75, 'labelled_images': 2, 'shippable': {},
                         'named_but_undetected': [],
                         'unqualified_tags': {
                             tag: {'reason': 'no_positive_examples', 'positive_count': 0, 'negative_count': 2}
                             for tag in CALIBRATION_TAGS}}


@pytest.mark.parametrize('source', ['det', 'gold', 'corpus'])
def test_calibration_cannot_overwrite_source(source, tmp_path):
    for name in ('det', 'gold', 'corpus'):
        (tmp_path / name).write_text('{"entries": []}')
    result = cli('calibrate_slice_tags', '--detections', tmp_path / 'det', '--golden', tmp_path / 'gold',
                 '--corpus', tmp_path / 'corpus', '--out', tmp_path / source, cwd=tmp_path)
    assert result.returncode != 0
    assert 'choose a new output' in result.stderr.lower()
    for name in ('det', 'gold', 'corpus'):
        assert (tmp_path / name).read_text() == '{"entries": []}'


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
