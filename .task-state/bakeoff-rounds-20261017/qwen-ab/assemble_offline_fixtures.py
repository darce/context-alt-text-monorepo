"""Assemble private test layouts from supplied exact bytes; no native imports/effects."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def assemble(supplied, workspace):
    supplied, workspace = Path(supplied), Path(workspace)
    pins = json.loads((supplied / 'pinned-input-index.json').read_bytes())
    for name, digest in pins.items():
        raw = (supplied / 'pinned-inputs' / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('supplied pin mismatch: ' + name)
    for dest in (workspace / 'references', workspace / 'qwen-ab/references'):
        if dest.exists():
            raise ValueError('private fixture directory already exists: ' + str(dest))
        shutil.copytree(supplied / 'qwen-ab/references', dest)
        for path in dest.rglob('*'):
            if path.is_file():
                path.chmod(path.stat().st_mode | 0o200)
        for name in pins:
            shutil.copyfile(supplied / 'pinned-inputs' / name, dest / name)
    for name in ('run_owner_root_fixture_r6.py', 'run_selected_root_resume_qualification.py',
                 'bakeoff_frontier_capacity.py'):
        dest = workspace / name
        if dest.exists():
            raise ValueError('fixture module already exists: ' + str(dest))
        shutil.copyfile(supplied / name, dest)
    layout = workspace / 'qwen-ab/workspace'
    layout.mkdir(exist_ok=True)
    (layout / 'prepare_qwen_ab.py').symlink_to('../prepare_qwen_ab.py')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--supplied', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    assemble(args.supplied, args.workspace)
