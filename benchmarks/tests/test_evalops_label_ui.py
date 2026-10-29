"""Synthetic packets only. Observable local labeling contract."""
import importlib.util
import json
import os
from pathlib import Path
import io
import http.client
import shutil
import subprocess

import pytest

SOURCE = Path(__file__).parents[1] / 'tools/evalops/label_ui.py'
spec = importlib.util.spec_from_file_location('label_ui', SOURCE)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


def packet():
    return dict(schema='evalops.label-packet.v1', packet_id='DEMO-batch',
                rubric_version='finding-rubric-v1', rubric='Review independently.',
                secret='never exposed', items=[dict(presentation_id='opaque-a',
                description='<script>claim</script>', file_path=None, line_start=None,
                line_end=None, source_context=None, context_status='unavailable',
                context_note='No frozen source available.', gold_label='defect')])


@pytest.fixture
def paths(tmp_path):
    p = tmp_path / 'packet.json'
    p.write_text(json.dumps(packet()))
    return p, tmp_path / 'state'


def decision(label='unclear', client_id='retry-1'):
    return dict(presentation_id='opaque-a', label=label, note='synthetic note', client_id=client_id,
                disposition='unknown', affected_action=None, blocking_reason=None,
                provenance=dict(kind='unknown', exposure='unknown', attestation_ref=None,
                                original_ref=None, protocol_version='demo-protocol-v2'))


def test_packet_projection_and_missing_context(paths):
    public = ui.load_packet(paths[0])
    assert public.get('packet_id') == 'DEMO-batch', 'packet must expose validated public packet fields'
    assert 'secret' not in public
    assert 'gold_label' not in public['items'][0]
    assert public['items'][0]['source_context'] is None
    assert public['items'][0]['context_status'] == 'unavailable'


@pytest.mark.parametrize('change', ['empty', 'duplicate', 'bad_context', 'bad_line'])
def test_packet_rejects_invalid(paths, change):
    p = packet()
    if change == 'empty': p['items'] = []
    if change == 'duplicate': p['items'] *= 2
    if change == 'bad_context': p['items'][0]['context_status'] = 'live'
    if change == 'bad_line': p['items'][0]['line_start'] = True
    paths[0].write_text(json.dumps(p))
    with pytest.raises(ValueError): ui.load_packet(paths[0])


@pytest.mark.parametrize('raw', ['{"schema":1,"schema":2}', '{"bad":NaN}'])
def test_strict_json(paths, raw):
    paths[0].write_text(raw)
    with pytest.raises(ValueError): ui.load_packet(paths[0])


def test_durable_identity_retry_correction_resume(paths, monkeypatch):
    s = ui.State(*paths, 'reviewer')
    try:
        with pytest.raises(ValueError): s.decide(decision())
        s.start({'annotator': 'Human A'})
        synced = []
        real = os.fsync
        monkeypatch.setattr(os, 'fsync', lambda fd: (synced.append(fd), real(fd))[1])
        first = s.decide(decision())
        assert synced, 'save must fsync before acknowledgment'
        assert first['label_source'] == 'human' and first['role'] == 'reviewer'
        assert first['annotator'] == 'Human A' and first['labeled_at'].endswith('Z')
        assert s.decide(decision()) == first
        with pytest.raises(ValueError): s.decide(decision('defect'))
        second = s.decide(decision('defect', 'retry-2'))
        assert second['supersedes'] == first['event_id']
        with pytest.raises(ValueError): s.start({'annotator': 'Other'})
        assert s.snapshot()['progress'] == {'answered': 1, 'total': 1}
        assert len(s.export().splitlines()) == 2
    finally: s.close()
    resumed = ui.State(*paths, 'reviewer')
    try:
        assert resumed.snapshot()['answers']['opaque-a']['label'] == 'defect'
        assert resumed.snapshot()['annotator'] == 'Human A'
        assert resumed.decide(decision('defect', 'retry-2')) == second
        assert len(resumed.export().splitlines()) == 2
    finally: resumed.close()


def test_independent_role_packet_and_exclusive_lock(paths):
    s = ui.State(*paths, 'reviewer')
    try:
        with pytest.raises(ValueError): ui.State(*paths, 'reviewer')
        s.start({'annotator': 'Reviewer Human'})
        s.decide(decision('defect'))
    finally: s.close()
    with pytest.raises(ValueError): ui.State(*paths, 'expert')
    expert_packet = packet(); expert_packet['packet_id'] = 'DEMO-expert'
    expert_path = paths[0].parent / 'expert-packet.json'
    expert_path.write_text(json.dumps(expert_packet))
    other = ui.State(expert_path, paths[1].parent / 'expert', 'expert')
    try:
        assert other.snapshot()['answers'] == {}
        assert other.export() == ''
        assert other.snapshot()['role'] == 'expert'
        assert other.snapshot()['packet']['packet_id'] == 'DEMO-expert'
    finally: other.close()
    p = packet(); p['packet_id'] = 'other'
    paths[0].write_text(json.dumps(p))
    with pytest.raises(ValueError): ui.State(*paths, 'reviewer')


def test_invalid_decisions_and_export_projection(paths):
    s = ui.State(*paths, 'reviewer')
    try:
        s.start({'annotator': 'Human'})
        for payload in [decision('yes'), dict(decision(), presentation_id='unknown'), dict(decision(), note='x'*5000)]:
            with pytest.raises(ValueError): s.decide(payload)
        s.decide(dict(decision(), gold_label='defect', secret='never'))
        assert 'gold_label' not in s.export() and 'secret' not in s.export()
    finally: s.close()


def test_corrupt_log_fails_loudly(paths):
    s = ui.State(*paths, 'reviewer'); s.close()
    (paths[1] / 'events.jsonl').write_text('{broken\n')
    with pytest.raises(ValueError): ui.State(*paths, 'reviewer')


@pytest.mark.parametrize('alias', ['direct', 'symlink', 'hardlink'])
def test_input_output_collision(paths, alias):
    p, d = paths; d.mkdir()
    target = d / 'events.jsonl'
    if alias == 'direct': target.write_bytes(p.read_bytes()); p = target
    if alias == 'symlink': target.symlink_to(p)
    if alias == 'hardlink': os.link(p, target)
    before = p.read_bytes()
    with pytest.raises(ValueError): ui.State(p, d, 'reviewer')
    assert p.read_bytes() == before


def test_http_origin_csrf_static_and_export(paths, monkeypatch):
    s = ui.State(*paths, 'reviewer')
    # Exercise real BaseHTTPRequestHandler parsing without sockets: this remote
    # sandbox prohibits socket creation. Binding itself remains runtime QA.
    class Server:
        def __init__(self, address, handler):
            assert address == ('127.0.0.1', 0)
            self.server_address = ('127.0.0.1', 8765)
            self.handler = handler
    class Connection:
        def __init__(self, raw): self.reader = io.BytesIO(raw); self.output = bytearray()
        def makefile(self, *args): return self.reader
        def sendall(self, raw): self.output.extend(raw)
        def settimeout(self, timeout): pass
    monkeypatch.setattr(ui.http.server, 'HTTPServer', Server)
    server = ui.make_server(s, 0)
    port = server.server_address[1]; origin = f'http://127.0.0.1:{port}'
    def request(method, path, body=None, headers=None):
        headers = dict(headers or {})
        headers.setdefault('Host', f'127.0.0.1:{port}')
        data = (body or '').encode()
        if body is not None: headers['Content-Length'] = str(len(data))
        raw = f'{method} {path} HTTP/1.0\r\n'.encode()
        raw += ''.join(f'{k}: {v}\r\n' for k, v in headers.items()).encode() + b'\r\n' + data
        conn = Connection(raw)
        server.handler(conn, ('127.0.0.1', 12345), server)
        class ResponseSocket:
            def makefile(self, *args): return io.BytesIO(conn.output)
        response = http.client.HTTPResponse(ResponseSocket()); response.begin()
        return response.status, response.read()
    try:
        code, raw = request('GET', '/api/session'); assert code == 200
        snap = json.loads(raw); assert 'gold_label' not in raw.decode()
        assert request('GET', '/api/session', headers={'Host': 'evil.example'})[0] == 403
        assert request('GET', '/../score_judge.py')[0] == 404
        assert request('GET', '/packet.json')[0] == 404
        assert request('GET', '/')[0] == 200
        assert request('GET', '/app.js')[0] == 200
        assert request('GET', '/%2e%2e/label_ui.py')[0] == 404
        assert request('POST', '/api/session', '{}')[0] == 403
        headers = {'Origin': origin, 'X-CSRF-Token': snap['csrf_token'], 'Content-Type': 'application/json'}
        wrong_token = dict(headers, **{'X-CSRF-Token': 'wrong'})
        assert request('POST', '/api/session', '{"annotator":"Human"}', wrong_token)[0] == 403
        assert request('POST', '/api/session', '{"annotator":"Human"}', headers)[0] == 200
        assert request('POST', '/api/decision', '{"label":"defect","label":"unclear"}', headers)[0] == 400
        assert request('POST', '/api/decision', json.dumps(decision()), headers)[0] == 200
        code, raw = request('GET', '/api/export'); assert code == 200
        assert json.loads(raw)['label_source'] == 'human'
        headers['Origin'] = 'http://evil.example'
        assert request('POST', '/api/decision', json.dumps(decision()), headers)[0] == 403
    finally:
        s.close()


@pytest.mark.parametrize('corruption', ['role', 'extra', 'truncated'])
def test_valid_json_corrupt_history_rejected(paths, corruption):
    s = ui.State(*paths, 'reviewer')
    s.start({'annotator': 'Human'})
    event = s.decide(decision()); s.close()
    if corruption == 'role': event['role'] = 'expert'
    if corruption == 'extra': event['gold_label'] = 'defect'
    raw = json.dumps(event) + ('\n' if corruption != 'truncated' else '')
    (paths[1] / 'events.jsonl').write_text(raw)
    with pytest.raises(ValueError): ui.State(*paths, 'reviewer')


def test_output_directory_symlink_rejected(paths):
    actual = paths[1].parent / 'actual'; actual.mkdir()
    paths[1].symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError): ui.State(*paths, 'reviewer')
    assert not list(actual.iterdir())


def test_legacy_restore_projection_export_and_correction(paths):
    """A frozen v1 event is read, never rewritten or reclassified."""
    import uuid
    s = ui.State(*paths, 'expert'); s.start({'annotator': 'DEMO legacy expert'}); s.close()
    event_id = str(uuid.uuid4())
    legacy = dict(presentation_id='opaque-a', label='defect', note='DEMO original', client_id='old-retry',
                  event_id=event_id, role='expert', annotator='DEMO legacy expert', packet_id='DEMO-batch',
                  rubric_version='finding-rubric-v1', label_source='human',
                  labeled_at='2026-10-29T00:00:00Z', supersedes=None)
    raw = (json.dumps(legacy, indent=None) + '\n').encode()
    journal = paths[1] / 'events.jsonl'; journal.write_bytes(raw)
    s = ui.State(*paths, 'expert')
    try:
        current = s.snapshot()['answers']['opaque-a']
        assert current['label'] == 'defect' and current['disposition'] == 'unknown'
        assert current['provenance'] == dict(kind='legacy_unknown', exposure='unknown',
                                           attestation_ref=None, original_ref=None, protocol_version=None)
        assert json.loads(s.export()) == current
        assert s.decide({k: legacy[k] for k in ('presentation_id', 'label', 'note', 'client_id')}) == legacy
        with pytest.raises(ValueError, match='Conflicting retry'):
            s.decide(dict(presentation_id='opaque-a', label='not_defect', note='DEMO original', client_id='old-retry'))
        assert journal.read_bytes() == raw
        with pytest.raises(ValueError, match='required'):
            s.decide(dict(presentation_id='opaque-a', label='defect', client_id='new-unstructured'))
        corrected = s.decide(decision('defect', 'new-correction'))
        assert corrected['supersedes'] == event_id and corrected['original_event_id'] == event_id
        assert journal.read_bytes().startswith(raw)
    finally: s.close()
    s = ui.State(*paths, 'expert')
    try:
        assert s.snapshot()['answers']['opaque-a'] == corrected
        assert journal.read_bytes().startswith(raw)
        assert len(s.export().splitlines()) == 2
    finally: s.close()


def test_assisted_provenance_roundtrip_retry_and_history(paths):
    s = ui.State(*paths, 'reviewer'); s.start({'annotator': 'DEMO human'})
    first = s.decide(decision('defect'))
    payload = decision('defect', 'assisted-correction')
    payload.update(disposition='nonblocking', affected_action='merge bounded rubric change')
    payload['provenance'].update(kind='user_assisted', exposure='exposed',
                                 original_ref=first['event_id'], attestation_ref='DEMO user adjudication receipt')
    corrected = s.decide(payload)
    assert corrected['label'] == 'defect' and corrected['disposition'] == 'nonblocking'
    assert corrected['supersedes'] == first['event_id'] == corrected['original_event_id']
    assert corrected['rubric_version'] == 'finding-rubric-v1'
    raw = (paths[1] / 'events.jsonl').read_bytes(); s.close()
    s = ui.State(*paths, 'reviewer')
    try:
        assert s.decide(payload) == corrected
        assert (paths[1] / 'events.jsonl').read_bytes() == raw
        assert s.snapshot()['answers']['opaque-a'] == corrected
        assert [json.loads(line) for line in s.export().splitlines()] == [first, corrected]
        for mutate in ('disposition', 'action', 'reason', 'provenance'):
            changed = json.loads(json.dumps(payload))
            if mutate == 'disposition': changed['disposition'] = 'unknown'
            if mutate == 'action': changed['affected_action'] = 'another action'
            if mutate == 'reason': changed['blocking_reason'] = 'different conditions'
            if mutate == 'provenance': changed['provenance']['exposure'] = 'unknown'
            with pytest.raises(ValueError, match='Conflicting retry'): s.decide(changed)
        assert (paths[1] / 'events.jsonl').read_bytes() == raw
    finally: s.close()


@pytest.mark.parametrize('label,disposition,action,reason', [
    ('defect', 'nonblocking', 'merge feature', None),
    ('defect', 'blocks', 'accept affected action', 'DEMO invariant fails under the specified condition'),
    ('defect', 'unknown', None, None),
    ('unclear', 'unknown', None, None),
    ('not_defect', 'unknown', None, None),
    ('unclear', 'nonblocking', 'unaffected merge', None),
])
def test_independent_validity_and_disposition(paths, label, disposition, action, reason):
    s = ui.State(*paths, 'reviewer'); s.start({'annotator': 'DEMO human'})
    try:
        payload = dict(decision(label), disposition=disposition, affected_action=action, blocking_reason=reason)
        saved = s.decide(payload)
        assert (saved['label'], saved['disposition'], saved['affected_action'], saved['blocking_reason']) == (label, disposition, action, reason)
        assert saved['provenance']['kind'] == 'unknown'
    finally: s.close()


@pytest.mark.parametrize('kind,exposure,reference', [
    ('blind_human', 'unexposed', None),
    ('user_assisted', 'unknown', None),
    ('post_review', 'exposed', None),
    ('independent_expert', 'unexposed', 'DEMO independent attestation'),
    ('unknown', 'unknown', None),
])
def test_provenance_is_explicit_not_inferred_from_role_or_note(paths, kind, exposure, reference):
    s = ui.State(*paths, 'expert'); s.start({'annotator': 'DEMO expert'})
    try:
        payload = decision(); payload['note'] = 'DEMO independent gold majority says so'
        payload['provenance'].update(kind=kind, exposure=exposure, attestation_ref=reference)
        saved = s.decide(payload)
        assert saved['provenance'] == payload['provenance']
        assert json.loads(s.export())['provenance']['kind'] == kind
        assert 'gold' not in saved
    finally: s.close()


@pytest.mark.parametrize('change', [
    {'disposition': 'blocks', 'affected_action': 'merge', 'blocking_reason': 'evidence'},
    {'label': 'not_defect', 'disposition': 'blocks', 'affected_action': 'merge', 'blocking_reason': 'evidence'},
    {'label': 'defect', 'disposition': 'blocks', 'affected_action': None, 'blocking_reason': 'evidence'},
    {'label': 'defect', 'disposition': 'blocks', 'affected_action': 'merge', 'blocking_reason': None},
    {'disposition': 'nonblocking'}, {'disposition': 'blocker'}, {'disposition': []},
    {'affected_action': ' '}, {'blocking_reason': 'x' * 4001}, {'affected_action': 'x' * 1025},
    {'provenance': None}, {'provenance': {'kind': 'blind_human'}},
])
def test_invalid_annotation_combinations_do_not_append(paths, change):
    s = ui.State(*paths, 'reviewer'); s.start({'annotator': 'DEMO human'})
    try:
        with pytest.raises(ValueError): s.decide(dict(decision(), **change))
        assert s.export() == ''
        assert (paths[1] / 'events.jsonl').read_bytes() == b''
    finally: s.close()


@pytest.mark.parametrize('change', [
    {'kind': 'blind_human'}, {'kind': 'independent_expert', 'exposure': 'unexposed'},
    {'kind': 'independent_expert', 'exposure': 'exposed', 'attestation_ref': 'DEMO ref'},
    {'kind': 'user_assisted', 'exposure': 'unexposed'},
    {'kind': 'post_review', 'exposure': 'unexposed'},
    {'kind': 'legacy_unknown'}, {'kind': []}, {'exposure': True},
    {'attestation_ref': 'x' * 1025}, {'original_ref': 'x' * 1025}, {'protocol_version': ''},
    {'protocol_version': None}, {'protocol_version': 'x' * 129}, {'gold': True},
])
def test_invalid_provenance_does_not_append(paths, change):
    s = ui.State(*paths, 'reviewer'); s.start({'annotator': 'DEMO human'})
    try:
        payload = decision(); payload['provenance'].update(change)
        with pytest.raises(ValueError): s.decide(payload)
        assert s.export() == ''
    finally: s.close()


@pytest.mark.parametrize('change', ['original', 'schema', 'provenance', 'disposition'])
def test_annotation_replay_rejects_tampering(paths, change):
    s = ui.State(*paths, 'reviewer'); s.start({'annotator': 'DEMO human'})
    event = s.decide(decision()); s.close()
    if change == 'original': event['original_event_id'] = 'wrong'
    if change == 'schema': event['annotation_schema'] = 'future-unknown'
    if change == 'provenance': event['provenance']['kind'] = 'blind_human'
    if change == 'disposition': event['disposition'] = 'blocks'
    (paths[1] / 'events.jsonl').write_text(json.dumps(event) + '\n')
    with pytest.raises(ValueError): ui.State(*paths, 'reviewer')


# Drives the shipped app.js in a Node VM. Element ids, required flags and
# select options come from index.html; the decision response is the event the
# real State returned for the exact payload the page posts.
DOM_HARNESS = r'''
'use strict';
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const elements = new Map(), radios = [];
let form = null, select = null;
for (const [, close, tag, rawAttrs] of fs.readFileSync(input.html, 'utf8').matchAll(/<(\/?)(\w+)([^>]*)>/g)) {
  if (close) { if (tag === 'form') form = null; if (tag === 'select') select = null; continue; }
  const attrs = Object.fromEntries([...rawAttrs.matchAll(/([\w-]+)(?:="([^"]*)")?/g)].map(([, k, v]) => [k, v ?? '']));
  if (tag === 'option' && select) { select.options.push(attrs.value); continue; }
  if (!attrs.id && attrs.name !== 'label') continue;
  const el = {id: attrs.id, form, value: attrs.value ?? '', hidden: 'hidden' in attrs, disabled: 'disabled' in attrs,
    required: 'required' in attrs, checked: false, textContent: '', className: '', listeners: {}, options: tag === 'select' ? [] : null,
    addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
    dispatch(type) { return (this.listeners[type] || []).map(fn => fn(event())); },
    focus() {},
    reportValidity() {
      const owned = [...elements.values(), ...radios].filter(e => e.form === this.id && e.required && !e.disabled);
      return owned.every(e => radios.includes(e) ? radios.some(r => r.checked) : e.value !== '');
    }};
  if (tag === 'form') form = attrs.id;
  if (tag === 'select') select = el;
  if (attrs.name === 'label') radios.push(el); else elements.set(attrs.id, el);
}
const $ = id => { if (!elements.has(id)) throw new Error(`index.html has no #${id}`); return elements.get(id); };
function event() { const e = {defaultPrevented: false, returnValue: undefined, preventDefault() { e.defaultPrevented = true; }}; return e; }
const windowListeners = {}, requests = [], replies = [...input.decision_replies];
let release = null, ids = 0;
const respond = reply => ({ok: reply.status < 400, status: reply.status, json: async () => JSON.parse(JSON.stringify(reply.body))});
function fetch(path, options) {
  const method = options.method || 'GET';
  requests.push({path, method, headers: options.headers || {}, body: options.body === undefined ? null : JSON.parse(options.body)});
  if (method === 'GET' && path === '/api/session') return Promise.resolve(respond({status: 200, body: input.session}));
  if (method === 'POST' && path === '/api/decision' && replies.length) {
    const reply = replies.shift();
    if (!reply.deferred) return Promise.resolve(respond(reply));
    return new Promise(resolve => { release = () => resolve(respond(reply)); });
  }
  return Promise.reject(new Error(`unexpected ${method} ${path}`));
}
const context = vm.createContext({
  document: {getElementById: id => elements.get(id) || null,
    querySelectorAll: selector => { if (selector !== '[name=label]') throw new Error(selector); return radios; },
    querySelector: selector => { if (selector !== '[name=label]:checked') throw new Error(selector); return radios.find(r => r.checked) || null; }},
  window: {addEventListener(type, fn) { (windowListeners[type] ||= []).push(fn); }},
  history: {replaceState() {}}, fetch, crypto: {randomUUID: () => `node-client-${++ids}`}});
const flush = () => new Promise(resolve => setImmediate(resolve));
function observe(step) {
  const unload = event(); for (const fn of windowListeners.beforeunload) fn(unload);
  return {step, screens: ['session', 'finding', 'complete'].filter(id => !$(id).hidden), unload_prevented: unload.defaultPrevented,
    summary: $('summary').textContent, decision_error: $('decision-error').hidden ? null : $('decision-error').textContent,
    save: $('save').textContent, save_disabled: $('save').disabled};
}
async function main() {
  vm.runInContext(fs.readFileSync(input.app, 'utf8'), context, {filename: input.app});
  await flush();
  const observations = [observe('loaded')];
  for (const [id, value] of Object.entries(input.fields)) {
    if (id === 'label') for (const radio of radios) radio.checked = radio.value === value;
    else { if ($(id).options && !$(id).options.includes(value)) throw new Error(`#${id} has no option ${value}`); $(id).value = value; }
    await Promise.all($('fields').dispatch('input'));
  }
  observations.push(observe('drafted'));
  for (let attempt = 0; attempt < input.decision_replies.length; attempt++) {
    if ($('save').disabled) throw new Error('Save is disabled');
    const handled = Promise.all($('decision-form').dispatch('submit'));
    await flush();
    if (release) { observations.push(observe('in_flight')); release(); release = null; }
    await handled;
    observations.push(observe(`reply_${attempt}`));
  }
  process.stdout.write(JSON.stringify({observations, requests}));
}
main().catch(error => { console.error(error.stack); process.exit(1); });
'''


@pytest.mark.parametrize('scenario', ['acknowledged', 'in_flight', 'failed_then_retry'])
def test_one_item_completion_unload_warning_tracks_unacknowledged_saves(paths, scenario):
    node = shutil.which('node')
    if node is None: pytest.skip('node is required to run label-ui/app.js against the DOM harness')
    s = ui.State(*paths, 'reviewer')
    try:
        session = s.start({'annotator': 'DEMO human'})
        expected = dict(presentation_id='opaque-a', label='defect', note='DEMO synthetic completion check',
                        client_id='node-client-1', disposition='nonblocking',
                        affected_action='DEMO merge label UI follow-up', blocking_reason=None,
                        provenance=dict(kind='blind_human', exposure='unexposed', attestation_ref=None,
                                        original_ref=None, protocol_version='evalops-annotation-v2'))
        saved = s.decide(expected)
    finally: s.close()
    acknowledged = dict(status=200, body=saved)
    replies = {'acknowledged': [acknowledged], 'in_flight': [dict(acknowledged, deferred=True)],
               'failed_then_retry': [dict(status=503, body={'error': 'DEMO storage unavailable.'}), acknowledged]}[scenario]
    fields = {'label': 'defect', 'disposition': 'nonblocking', 'affected-action': expected['affected_action'],
              'provenance-kind': 'blind_human', 'exposure': 'unexposed', 'note': expected['note']}
    assets = SOURCE.parent / 'label-ui'
    run = subprocess.run([node, '-e', DOM_HARNESS], capture_output=True, text=True, timeout=60, check=False,
                         input=json.dumps(dict(app=str(assets / 'app.js'), html=str(assets / 'index.html'),
                                               session=session, decision_replies=replies, fields=fields)))
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    posts = [r for r in result['requests'] if r['path'] == '/api/decision']
    assert [p['body'] for p in posts] == [expected] * len(replies), 'page must post (and retry) the payload State accepted'
    assert all(p['headers']['X-CSRF-Token'] == session['csrf_token'] for p in posts)
    steps = {o['step']: o for o in result['observations']}
    assert steps['loaded']['screens'] == ['finding'] and not steps['loaded']['unload_prevented']
    assert steps['drafted']['unload_prevented'], 'an unsaved draft must still warn'
    if scenario == 'in_flight':
        assert steps['in_flight']['screens'] == ['finding'] and steps['in_flight']['save_disabled']
        assert steps['in_flight']['unload_prevented'], 'a save without acknowledgment must still warn'
    if scenario == 'failed_then_retry':
        failed = steps['reply_0']
        assert failed['screens'] == ['finding'] and 'DEMO storage unavailable.' in failed['decision_error']
        assert failed['unload_prevented'], 'a failed save awaiting retry must still warn'
    final = steps[f'reply_{len(replies) - 1}']
    assert final['screens'] == ['complete']
    assert final['summary'].startswith('1 of 1 findings answered · 0 unanswered.')
    assert not final['unload_prevented'], 'acknowledged final save must not leave a pending unload warning'
