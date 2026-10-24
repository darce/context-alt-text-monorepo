"""RAW-GENERATION paired producer v2; importing performs no I/O.

Exact parent: extraction_paired_client.py SHA256
5c89754916884fc3448e00067e40afab4fd0f850bb430200a7a74c82bafc1838.
Prospective timeout-only revision; old consumer pins do not adopt this source.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def message_sha(messages):
    return sha(json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def extraction_prompt(base, lex, enabled=False):
    if type(enabled) is not bool:
        raise ValueError('extraction_lexicon must be a boolean')
    return base + '\n\n' + lex.render() if enabled else base


def extraction_messages(b, client, lex, enabled, image_part):
    return [dict(role='system', content=extraction_prompt(b._PASS1_SYSTEM_PROMPT, lex, enabled)),
            dict(role='user', content=[image_part, dict(type='text', text=client._pass1_user_text())])]


def load_resources(cfg):
    override = Path(cfg['loader_override'])
    if sha(override.read_bytes()) != cfg['loader_sha256']:
        raise ValueError('Loader digest mismatch')
    sys.path.insert(0, cfg['service_dir'])
    name = 'scripts.eval_harness.depiction_lexicon'
    spec = importlib.util.spec_from_file_location(name, override)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from scripts.eval_harness import bakeoff as b
    lex = module.load_depiction_lexicon(cfg['canon_root'])
    if lex.sha256 != cfg['canon_sha256'] or lex.version != 'canon v0.26.2' or len(lex.rules) != 17:
        raise ValueError('Canon identity mismatch')
    return b, lex


class ModelMismatch(RuntimeError):
    pass


def run(cfg, *, out, keyfile, model_id, dry_run=False, b=None, lex=None, transport=None):
    """Run with real builders; optional MockTransport supplies the only HTTP boundary."""
    timeout_s = cfg.get('timeout_s', 600)
    if type(timeout_s) is not int or not 60 <= timeout_s <= 1800:
        raise ValueError('timeout_s must be an integer within 60..1800')
    enabled = cfg.get('extraction_lexicon', False)
    if type(enabled) is not bool:
        raise ValueError('extraction_lexicon must be a boolean')
    if b is None or lex is None:
        b, lex = load_resources(cfg)
    stage_prompt = extraction_prompt(b._PASS1_SYSTEM_PROMPT, lex, enabled)
    output = Path(out)
    record = dict(schema='description-raw-generation-paired-run/v2',
                  producer_version='raw-generation-paired/v2', timeout_s=timeout_s,
                  recipe='v3-extraction-lexicon-shared-facts-image-writing-pair/v1',
                  extraction_lexicon=enabled, extraction_arm='on' if enabled else 'off',
                  writing_arms=['off', 'on'], model_id=model_id,
                  model_version=cfg['model_version'], model_revision=cfg['model_revision'],
                  canon=lex.provenance(), loader_sha256=cfg['loader_sha256'],
                  producer_sha256=sha(Path(__file__).read_bytes()),
                  bakeoff_source_sha256=sha(Path(b.__file__).read_bytes()),
                  identity_policy='withheld_until_AuraFace_FIR', context_pack={},
                  no_face_annotation_or_identity_evaluation=True,
                  extraction_system_sha256=sha(stage_prompt), items=[], envelopes=[],
                  request_budget=3*len(cfg['images']), post_attempts=0,
                  completed=False, dry_run=dry_run, error=None)
    key = None if dry_run else b._load_server_api_key(keyfile)

    class ObservedClient(b.BakeoffClient):
        def _request_dict(self, *args, **kwargs):
            value = super()._request_dict(*args, **kwargs)
            record['envelopes'].append(self._redact_response(value))
            if value.get('model') != model_id:
                raise ModelMismatch('Response model mismatch; no further inference permitted')
            return value

    clients = {}
    clean_items = []
    def snapshot():
        # Apply the inherited bounded scrubber per artifact, not to an unbounded
        # aggregate: a full 120-image run must not exhaust its per-response cap.
        redact = clients['off']._redact_response
        cleaned = redact({k: v for k, v in record.items() if k not in ('items', 'envelopes')})
        # Items are finalized before persistence; envelopes are scrubbed at capture.
        # Cache finalized artifacts so persistence does not repeatedly scrub N^2 rows.
        for row in record['items'][len(clean_items):]:
            clean_items.append(redact(row))
        cleaned['items'] = list(clean_items)
        cleaned['envelopes'] = list(record['envelopes'])
        return cleaned

    def persist():
        cleaned = snapshot()
        temporary = output.with_suffix('.partial.tmp')
        with temporary.open('w') as stream:
            json.dump(cleaned, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o400)
        os.replace(temporary, output)

    def observed(request):
        if request.method != 'POST' or request.url.path != '/v1/chat/completions':
            raise RuntimeError('Unexpected request')
        if dry_run or record['post_attempts'] >= record['request_budget']:
            raise RuntimeError('Completion budget exhausted')
        record['post_attempts'] += 1

    try:
        for arm in ['off', 'on']:
            client = ObservedClient(cfg['endpoint'], model_id=model_id,
                model_version=cfg['model_version'], model_revision=cfg['model_revision'],
                server_api_key=key, seed=0, no_think=True, timeout_s=timeout_s,
                eval_mode='name_ablation', entry_traits={}, roster=[], prompt_variant='v3',
                caption_length='standard', two_pass=True,
                depiction_lexicon=lex if arm == 'on' else None, transport=transport)
            clients[arm] = client
            client._max_rate_limit_retries = 0
            private = [str(keyfile), Path(keyfile).name, str(output)]
            private += [str(i['path']) for i in cfg['images']]
            private += [str(cfg[k]) for k in ('service_dir', 'loader_override', 'canon_root') if k in cfg]
            client._response_private_values += tuple(dict.fromkeys(v for v in private if v))
            client._client.event_hooks['request'].append(observed)
        for image in cfg['images']:
            row = dict(image_id=image['image_id'], input_sha256=image['sha256'],
                       source_cluster=image.get('source_cluster', image['image_id']),
                       shared_extraction=[], arms={}, error=None, stage_prompts={})
            record['items'].append(row)
            try:
                data = Path(image['path']).read_bytes()
                if sha(data) != image['sha256']:
                    raise ValueError('Image digest mismatch')
                part = {'type': 'image_url', 'image_url': {'url': b._data_url(data, Path(image['path']).name)}}
                messages = extraction_messages(b, clients['off'], lex, enabled, part)
                def stamp(label, msgs):
                    row['stage_prompts'][label] = dict(system_sha256=sha(msgs[0]['content']),
                                                       messages_sha256=message_sha(msgs))
                stamp('extraction_' + record['extraction_arm'], messages)
                if dry_run:
                    for arm, client in clients.items():
                        stamp('writing_' + arm, client._weave_messages('{"people": []}', {}, image_part=part))
                    row['writer_hash_facts_placeholder'] = True
                    continue
                facts = clients['off']._timed_chat(messages, pass_name='describe_facts',
                    passes=row['shared_extraction'], max_tokens=b._PASS1_MAX_TOKENS)
                row['raw_facts_sha256'] = sha(facts)
                clients['off']._parse_response(b._parse_pass1_json, facts)
                order = ['off', 'on'] if int(image['sha256'][-1], 16) % 2 == 0 else ['on', 'off']
                row['writing_order'] = order
                for arm in order:
                    client = clients[arm]
                    result = dict(error=None, passes=[], writing_lexicon=arm == 'on')
                    row['arms'][arm] = result
                    msgs = client._weave_messages(facts, {}, image_part=part)
                    stamp('writing_' + arm, msgs)
                    try:
                        text = client._timed_chat(msgs, pass_name='ground_weave',
                            passes=result['passes'], max_tokens=b.WEAVE_MAX_TOKENS['standard'])
                        result['surfaces'] = client._parse_response(b._parse_three_surface_json, text)
                        result['configuration'] = client.run_configuration()
                    except ModelMismatch:
                        raise
                    except Exception as exc:
                        result['error'] = client._redact_response(f'{type(exc).__name__}: {exc}')
                row['error'] = '; '.join(f'{a}: {r["error"]}' for a, r in row['arms'].items() if r['error']) or None
            except ModelMismatch as exc:
                row['error'] = str(exc)
                raise
            except Exception as exc:
                row['error'] = clients['off']._redact_response(f'{type(exc).__name__}: {exc}')
            finally:
                persist()
        record['valid_pairs'] = sum(not r['error'] and len(r['arms']) == 2 for r in record['items'])
        record['completed'] = not dry_run and record['valid_pairs'] == len(cfg['images'])
    except Exception as exc:
        if clients:
            record['error'] = clients['off']._redact_response(f'{type(exc).__name__}: {exc}')
        else:
            raise
    finally:
        if clients:
            persist()
        for client in clients.values():
            client.close()
    return snapshot()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('config', 'out', 'keyfile', 'model-id'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    record = run(json.loads(Path(args.config).read_bytes()), out=args.out,
                 keyfile=args.keyfile, model_id=args.model_id, dry_run=args.dry_run)
    return 0 if (record['completed'] or args.dry_run and not record['error'] and
                 all(not r['error'] for r in record['items'])) else 1


if __name__ == '__main__':
    raise SystemExit(main())
