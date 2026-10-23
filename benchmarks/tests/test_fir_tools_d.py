"""Cheap portability and Git data-boundary regressions; never run measurements."""
from pathlib import Path
import os
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'benchmarks/tools/openimages_occlusion_measure.sh'


def run_shell(*args, cwd, env=None):
    clean = os.environ.copy()
    clean.pop('OPENIMAGES_ANNOTATION_DIR', None)
    clean.update(env or {})
    return subprocess.run(['bash', str(SCRIPT), *args], cwd=cwd, env=clean,
                          capture_output=True, text=True)


def test_shell_syntax():
    subprocess.run(['bash', '-n', str(SCRIPT)], check=True)


def test_help_without_inputs(tmp_path):
    result = run_shell('--help', cwd=tmp_path)
    assert result.returncode == 0
    assert 'OPENIMAGES_ANNOTATION_DIR' in result.stdout
    assert 'Usage:' in result.stdout


def test_missing_argument(tmp_path):
    result = run_shell(cwd=tmp_path)
    assert result.returncode != 0
    assert 'annotation directory is required' in result.stderr
    assert not result.stdout


@pytest.mark.parametrize('use_env', [False, True])
def test_invalid_directory(tmp_path, use_env):
    missing = str(tmp_path / 'absent')
    result = run_shell(*( [] if use_env else [missing]), cwd=tmp_path,
                       env={'OPENIMAGES_ANNOTATION_DIR': missing} if use_env else {})
    assert result.returncode != 0
    assert 'annotation directory does not exist' in result.stderr
    assert not result.stdout


def test_missing_csv_preflight(tmp_path):
    result = run_shell(str(tmp_path), cwd=tmp_path)
    assert result.returncode != 0
    assert 'required annotation CSV' in result.stderr
    assert not result.stdout


@pytest.mark.parametrize('path,ignored', [
    ('benchmarks/tools/build_corpus_manifest.py', False),
    ('benchmarks/tools/golden.py', False),
    ('benchmarks/tools/openimages_occlusion_measure.sh', False),
    ('benchmarks/tests/test_fir_tools_d.py', False),
    ('benchmarks/README.md', False),
    ('benchmarks/reports/openimages-occlusion-MEASUREMENTS.md', False),
    ('benchmarks/images/private.jpg', True),
    ('benchmarks/tools/output.json', True),
    ('benchmarks/tools/__pycache__/tool.pyc', True),
    ('benchmarks/results/run.json', True),
    ('benchmarks/tools/build_manifest.py', True),
    ('benchmarks/manifests/new-run.json', True),
    ('benchmarks/manifests/corpus-manifest-v3.json', False),
])
def test_ignore_policy(tmp_path, path, ignored):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_bytes((ROOT / '.gitignore').read_bytes())
    result = subprocess.run(['git', 'check-ignore', '--no-index', '-q', path], cwd=tmp_path)
    assert result.returncode == (0 if ignored else 1)
