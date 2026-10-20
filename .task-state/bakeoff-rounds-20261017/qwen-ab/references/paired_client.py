"""Bounded paired benchmark; existing v3 builders, one shared fact extraction.

Executed remotely as gate. No identities, face labels, or golden captions are
fabricated. Both writing arms receive the identical image and facts.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('--config', required=True)
parser.add_argument('--out', required=True)
parser.add_argument('--keyfile', required=True)
parser.add_argument('--model-id', required=True)
parser.add_argument('--dry-run', action='store_true')
args = parser.parse_args()
cfg = json.loads(Path(args.config).read_bytes())
sys.path.insert(0, cfg['service_dir'])
override = Path(cfg['loader_override'])
assert hashlib.sha256(override.read_bytes()).hexdigest() == cfg['loader_sha256']
name = 'scripts.eval_harness.depiction_lexicon'
spec = importlib.util.spec_from_file_location(name, override)
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
from scripts.eval_harness import bakeoff as b

lex = module.load_depiction_lexicon(cfg['canon_root'])
assert lex.sha256 == cfg['canon_sha256'] and lex.version == 'canon v0.26.2'
assert len(lex.rules) == 17
output = Path(args.out)
record = dict(schema='description-lexicon-paired-run/v1', model_id=args.model_id,
              model_revision=cfg['model_revision'], recipe='v3-shared-facts-image-both-arms',
              identity_policy='withheld_until_AuraFace_FIR', context_pack={},
              canon=lex.provenance(), loader_sha256=cfg['loader_sha256'],
              no_face_annotation_or_identity_evaluation=True, items=[], post_attempts=0,
              request_budget=3*len(cfg['images']), completed=False)

def persist():
    temporary = output.with_suffix('.partial.tmp')
    with temporary.open('w') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o400)
    os.replace(temporary, output)

key = '-' if args.dry_run else b._load_server_api_key(args.keyfile)
clients = {arm: b.BakeoffClient(cfg['endpoint'], model_id=args.model_id,
             model_version=cfg['model_version'], model_revision=cfg['model_revision'],
             server_api_key=None if args.dry_run else key, seed=0, no_think=True,
             timeout_s=60, eval_mode='name_ablation', entry_traits={}, roster=[],
             prompt_variant='v3', caption_length='standard', two_pass=True,
             depiction_lexicon=lex if arm == 'on' else None) for arm in ['off', 'on']}
key = None
for client in clients.values():
    client._max_rate_limit_retries = 0
    client._response_private_values += (args.keyfile, Path(args.keyfile).name)
    def request_observed(request):
        assert request.method == 'POST' and request.url.path == '/v1/chat/completions'
        assert record['post_attempts'] < record['request_budget'], 'Completion budget exhausted'
        record['post_attempts'] += 1
    client._client.event_hooks['request'].append(request_observed)

original_parse = b.BakeoffClient._parse_response
sequence = 0

def parse_observed(self, parse, value):
    global sequence
    if isinstance(value, dict) and 'choices' in value:
        cleaned = self._redact_response(value)
        with (output.parent / f'completion-envelope-{sequence:04d}.json').open('x') as stream:
            json.dump(cleaned, stream); stream.flush(); os.fsync(stream.fileno())
        (output.parent / f'completion-envelope-{sequence:04d}.json').chmod(0o400)
        sequence += 1
        if value.get('model') != args.model_id:
            raise SystemExit('Response model mismatch; no further inference permitted')
    return original_parse(self, parse, value)

b.BakeoffClient._parse_response = parse_observed
try:
    for image in cfg['images']:
        started = time.monotonic()
        data = Path(image['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == image['sha256']
        image_part = {'type':'image_url', 'image_url':{'url':b._data_url(data, Path(image['path']).name)}}
        dummy = {arm: client._weave_messages('{"people": []}', {}, image_part=image_part)
                 for arm, client in clients.items()}
        assert dummy['off'][1:] == dummy['on'][1:]
        assert dummy['on'][0]['content'].replace('\n\n' + lex.render(), '', 1) == dummy['off'][0]['content']
        if args.dry_run:
            record['items'].append(dict(image_id=image['image_id'], source_sha256=image['sha256'],
                 paired_image_and_context_equal=True, treatment_only_system_addendum=True,
                 prompt_fingerprints={arm:c.prompt_sha256 for arm,c in clients.items()}))
            continue
        row = dict(image_id=image['image_id'], input_sha256=image['sha256'],
                   source_cluster=image.get('source_cluster', image['image_id']),
                   arms={}, error=None, shared_extraction=[], describe={'passes':[]})
        facts = None
        try:
            client = clients['off']
            facts = client._timed_chat([
                {'role':'system','content':b._PASS1_SYSTEM_PROMPT},
                {'role':'user','content':[image_part,{'type':'text','text':client._pass1_user_text()}]}],
                pass_name='describe_facts', passes=row['shared_extraction'], max_tokens=b._PASS1_MAX_TOKENS)
            client._parse_response(b._parse_pass1_json, facts)
        except Exception as exc:
            row['error'] = client._redact_response(f'{type(exc).__name__}: {exc}')
        row['describe']['passes'].extend(row['shared_extraction'])
        order = ['off', 'on'] if int(image['sha256'][-1],16) % 2 == 0 else ['on','off']
        row['writing_order'] = order
        for arm in order:
            client = clients[arm]; passes=[]
            result=dict(error=row['error'], describe=None)
            if row['error'] is None or facts is not None and row['shared_extraction'][-1].get('raw'):
                # A malformed extraction must never be woven as valid facts.
                try:
                    client._parse_response(b._parse_pass1_json, facts)
                    text = client._timed_chat(client._weave_messages(facts, {}, image_part=image_part),
                        pass_name='ground_weave', passes=passes, max_tokens=b.WEAVE_MAX_TOKENS['standard'])
                    surfaces = client._parse_response(b._parse_three_surface_json, text)
                    result = dict(error=None, describe=dict(
                        alt_text_title=surfaces['title'], alt_text_draft=surfaces['alt'],
                        alt_text_long=surfaces['caption'], **client.run_configuration(),
                        passes=passes, tokens=b._sum_usage(passes)))
                except Exception as exc:
                    result['error'] = client._redact_response(f'{type(exc).__name__}: {exc}')
            result['passes'] = passes
            result['writing_latency_s'] = sum(x['latency_s'] for x in passes)
            row['arms'][arm] = result
            row['describe']['passes'].extend(passes)
        row['error'] = '; '.join(f'{arm}: {r["error"]}' for arm,r in row['arms'].items() if r['error']) or None
        row['latency_s'] = round(time.monotonic()-started,3)
        row['shared_extraction_latency_s'] = sum(x['latency_s']for x in row['shared_extraction'])
        record['items'].append(row)
        persist()
    record['completed'] = True
    record['valid_pairs'] = sum(not r.get('error') for r in record['items'])
    record['dry_run'] = args.dry_run
    persist()
finally:
    for client in clients.values():client.close()
