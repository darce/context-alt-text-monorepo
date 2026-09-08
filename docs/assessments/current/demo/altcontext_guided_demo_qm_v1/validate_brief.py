#!/usr/bin/env python3
"""Validate the handoff artifacts, not the application or proposed acceptance tests."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys

try:
    from jsonschema import Draft202012Validator
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit('Install validation dependencies: python -m pip install jsonschema beautifulsoup4')


def main() -> int:
    root = Path(__file__).resolve().parent
    brief = json.loads((root / 'implementation-brief.json').read_text(encoding='utf-8'))
    schema = json.loads((root / 'implementation-brief.schema.json').read_text(encoding='utf-8'))
    errors: list[str] = []
    Draft202012Validator.check_schema(schema)
    for err in Draft202012Validator(schema).iter_errors(brief):
        errors.append(f'Schema {list(err.absolute_path)}: {err.message}')

    def ids(collection: str, key: str = 'id') -> set[str]:
        values = [x[key] for x in brief[collection]]
        if len(values) != len(set(values)):
            errors.append(f'Duplicate IDs in {collection}')
        return set(values)

    source_ids = ids('sources')
    rule_ids = ids('canon_rules')
    evidence_ids = ids('evidence_anchors')
    finding_ids = ids('findings')
    test_ids = ids('acceptance_tests')
    task_ids = ids('work_items')
    ids('canon_scope_decisions')
    ids('target_test_hooks', 'test_id')

    def refs(owner: str, items: list[str], allowed: set[str]) -> None:
        missing = set(items) - allowed
        if missing:
            errors.append(f'{owner}: unknown references {sorted(missing)}')

    for rule in brief['canon_rules']:
        refs(rule['id'], [rule['source_id']], source_ids)
    for exception in brief['canon_scope_decisions']:
        refs(exception['id'], [exception['rule_id']], rule_ids)
    for f in brief['findings']:
        refs(f['id'], f['rule_ids'], rule_ids)
        refs(f['id'], f['evidence_ids'], evidence_ids)
        refs(f['id'], f['acceptance_test_ids'], test_ids)
    assigned_findings: set[str] = set()
    assigned_tests: set[str] = set()
    for w in brief['work_items']:
        refs(w['id'], w['depends_on'], task_ids)
        refs(w['id'], w['finding_ids'], finding_ids)
        refs(w['id'], w['acceptance_test_ids'], test_ids)
        refs(w['id'], w['copy_keys'], set(brief['copy_catalog']))
        assigned_findings.update(w['finding_ids'])
        assigned_tests.update(w['acceptance_test_ids'])
    if finding_ids - assigned_findings:
        errors.append('A finding has no implementing work item')
    if test_ids - assigned_tests:
        errors.append('An acceptance test has no work-item owner')

    pending = {w['id']: set(w['depends_on']) for w in brief['work_items']}
    order: list[str] = []
    while pending:
        ready = sorted(k for k, deps in pending.items() if not deps)
        if not ready:
            errors.append('Task dependencies contain a cycle')
            break
        order.extend(ready)
        for k in ready:
            del pending[k]
        for deps in pending.values():
            deps.difference_update(ready)

    raw = (root / 'source-snapshot.html').read_bytes()
    expected_hash = brief['sources'][0]['sha256']
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        errors.append('Source snapshot checksum mismatch')
    soup = BeautifulSoup(raw.decode('utf-8'), 'html.parser')
    for e in brief['evidence_anchors']:
        refs(e['id'], [e['source_id']], source_ids)
        nodes = soup.select(e['selector'])
        texts = [n.get_text(' ', strip=True) for n in nodes]
        if len(nodes) != e['match_count_in_snapshot'] or texts != e['text_matches']:
            errors.append(f"Source anchor drift: {e['id']}")
        if e.get('excerpt') and not any(e['excerpt'] in t for t in texts):
            errors.append(f"Excerpt absent: {e['id']}")
    if json.loads((root / 'copy.en.json').read_text()) != brief['copy_catalog']:
        errors.append('Copy export is not identical to the canonical catalog')
    exported = json.loads((root / 'evidence-anchors.json').read_text())
    if exported != {'source_sha256': expected_hash, 'anchors': brief['evidence_anchors']}:
        errors.append('Evidence export differs from the brief')
    if any(x['execution_status'] != 'not_run' for x in brief['acceptance_tests']):
        errors.append('A planning artifact incorrectly claims an executed acceptance test')

    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print(f"PASS: schema, references, {len(brief['evidence_anchors'])} DOM anchors, source checksum, copy export and dependency graph.")
    print('Valid task order: ' + ' -> '.join(order))
    print('Application acceptance tests: NOT RUN. This validator only checks the handoff package.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
