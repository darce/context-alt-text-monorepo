"""Check the frozen snapshot and code-to-axial conservation without printing source text."""
import hashlib
import json
import sys
from pathlib import Path

base = Path(__file__).resolve().parent
raw = Path(sys.argv[1]).read_bytes()
manifest = json.loads((base / 'manifest.json').read_text())
mapping = json.loads((base / 'axial-mapping.json').read_text())['mapping']
json.loads((base / 'schema.json').read_text())
assert hashlib.sha256(raw).hexdigest() == manifest['input_sha256']
source = json.loads(raw)
coded = [json.loads(line) for line in (base / 'open-coded.jsonl').read_text().splitlines()]
by_id = {row['id']: row for row in source}
assert len(by_id) == len(source) == len(coded) == manifest['record_count']
assert len({row['source_id'] for row in coded}) == len(coded)
assert {row['source_id'] for row in coded} == set(by_id)
assert sum(row['occurrence_count'] for row in coded) == sum(row['occurrence_count'] for row in source) == manifest['occurrence_count']
for record in coded:
    original = by_id[record['source_id']]
    canonical = json.dumps(original, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    assert record['source_row_sha256'] == hashlib.sha256(canonical).hexdigest()
    assert record['original_summary_sha256'] == hashlib.sha256((original['summary'] or '').encode()).hexdigest()
    assert record['original_summary_ref'] == {'snapshot': 'agent-errors.json', 'source_id': original['id'], 'field': 'summary'}
    assert all(record[key] == original[key] for key in ('created_at', 'last_seen_at', 'occurrence_count'))
    assert all(code in mapping for code in record['open_codes'])
    assert record['incident_group_id'] is None and record['incident_link_status'] == 'unknown'
assert set(mapping) == {code for record in coded for code in record['open_codes']}
print(f"Verified {len(coded)} records and {manifest['occurrence_count']} occurrences; incident links remain unknown.")
