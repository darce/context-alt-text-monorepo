"""Read-only provenance verification; never imports production or launches it."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT = Path('/home/gate/description-owner-ipc-repair-inputs-20261024T0532')
REFERENCES = HERE.parents[3] / 'references'
JOIN = Path('/home/gate/description-owner-ipc-join-20261024T0408/code')
CANON = Path('/home/gate/heuristics-canon-v0.26.2')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest = INPUT / 'manifest.json'
    assert digest(manifest) == '6038b6e69ddfb87248bcd44a320cf749a0e19d2088a69220d95042e925f9e123'
    for name, expected in json.loads(manifest.read_bytes())['files'].items():
        assert digest(INPUT / name) == expected, name
    joined = REFERENCES / 'joined-manifest.json'
    controls = next(row for row in json.loads(joined.read_bytes())['candidate_and_controls'] if row['role'] != 'candidate')
    for name, expected in controls['files'].items():
        assert digest(JOIN / name) == expected, name
    assert digest(CANON / 'lexicons/engineering.md') == '20e2cfe911755dfbd983b48e7b93be9cb46674f0ec0bce3dfec45a75a25fce6d'
    assert digest(CANON / 'lexicons/graph-theory.md') == '23bdbc8262cbd3577e4fd5ef3e49c6ad1f50fdfd1472ba3990497ef57e3eb61c'
    assert digest(CANON / 'PRINCIPLES.md') == '0bd3555fa6b97cadd02563f87ac292cb97ce34df960e6361fa82beaf9a07f205'
    paths = [manifest, joined, INPUT / 'window-operation-snapshot.json',
             CANON / 'lexicons/engineering.md', CANON / 'lexicons/graph-theory.md', CANON / 'PRINCIPLES.md',
             CANON / 'reasoning/falsification-disconfirmers.md', CANON / 'reasoning/measurement-integrity.md', CANON / 'reasoning/feedback-bounded-waiting.md']
    paths += [Path('/home/gate/description-gpu-start-inputs-20261023T2155/distilled') / name for name in ('pragmatic-programmer.md', 'implementing-effective-code-reviews.md', 'building-knowledge-graphs.md')]
    paths += [Path('/home/gate/workbay-inputs/uxrec-map-next-20261024/subject/literature/extracted/refactoring/distilled') / name for name in ('why-programs-fail.md', 'debugging-9-rules.md')]
    paths += sorted(REFERENCES.glob('*.json'))
    report = dict(input_files_verified=64, independent_control_files_verified=len(controls['files']), independent_controls_commit=controls['source_commit'], budget_seed='e1b7e1216d5416373bf625797866517f96ec47f1', copied_seed_commit='68a1981', files={str(p):digest(p) for p in paths}, effects='isolated local temporary files/processes only', canon_original_pin_gap='Available refactoring originals differ from requested engineering digests; no claim of engineering7975930e/51c51e6b bytes.')
    (HERE / 'evidence/provenance.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print('Verified 64 immutable input files and', len(controls['files']), 'independent control files; recorded exact provenance hashes.')


if __name__ == '__main__':
    main()
