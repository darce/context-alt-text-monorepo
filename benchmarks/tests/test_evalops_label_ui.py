"""Synthetic packets only. Observable local labeling contract."""
import importlib.util
import json
import os
from pathlib import Path
import io
import http.client

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
    return dict(presentation_id='opaque-a', label=label, note='synthetic note', client_id=client_id)


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
