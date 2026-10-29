"""Private stdlib finding labeler. Raw human events require an offline scorer join."""
from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import uuid

MAX_PACKET = 8 * 1024 * 1024
MAX_LOG = 64 * 1024 * 1024
LABELS = {'defect', 'not_defect', 'unclear'}
ANNOTATION_SCHEMA = 'evalops.annotation.v2'
ANNOTATION_FIELDS = {'disposition', 'affected_action', 'blocking_reason', 'provenance'}
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8')}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def strict_json(raw):
    def pairs(entries):
        result = {}
        for k, v in entries:
            require(k not in result, 'Duplicate JSON key')
            result[k] = v
        return result
    def constant(_):
        raise ValueError('Nonfinite JSON number')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, RecursionError, json.JSONDecodeError) as e:
        raise ValueError('Invalid JSON') from e


def text(value, limit, name, empty=False):
    require(isinstance(value, str) and len(value) <= limit and (empty or bool(value.strip())),
            f'{name}: invalid or too long')
    require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value), f'{name}: invalid Unicode')
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def load_packet(path):
    require(stat.S_ISREG(Path(path).stat().st_mode), 'Packet must be a regular file')
    with open(path, 'rb') as f:
        raw = f.read(MAX_PACKET + 1)
    require(len(raw) <= MAX_PACKET, 'Packet too large')
    p = strict_json(raw)
    require(isinstance(p, dict) and p.get('schema') == 'evalops.label-packet.v1', 'Invalid packet schema')
    result = {'schema': p['schema']}
    for key, limit in [('packet_id', 128), ('rubric_version', 128), ('rubric', 16000)]:
        result[key] = text(p.get(key), limit, key)
    items = p.get('items')
    require(isinstance(items, list) and 0 < len(items) <= 1000, 'Packet needs 1–1000 items')
    result['items'] = []; seen = set()
    for item in items:
        require(isinstance(item, dict), 'Invalid item')
        row = {}
        row['presentation_id'] = text(item.get('presentation_id'), 128, 'presentation_id')
        require(row['presentation_id'] not in seen, 'Duplicate presentation_id')
        seen.add(row['presentation_id'])
        row['description'] = text(item.get('description'), 16000, 'description')
        for key, limit in [('file_path', 1024), ('source_context', 64000)]:
            value = item.get(key)
            row[key] = None if value is None else text(value, limit, key, empty=True)
        for key in ['line_start', 'line_end']:
            value = item.get(key)
            require(value is None or (type(value) is int and 0 < value <= 10000000), 'Invalid source line')
            row[key] = value
        require(row['line_end'] is None or row['line_start'] is None or row['line_end'] >= row['line_start'], 'Reversed lines')
        status = item.get('context_status')
        require(status in ('verified_recorded_commit', 'unavailable'), 'Invalid context status')
        require(status != 'verified_recorded_commit' or bool(row['source_context']), 'Verified context requires code')
        require(status != 'unavailable' or row['source_context'] is None, 'Unavailable context must be null')
        row['context_status'] = status
        row['context_note'] = text(item.get('context_note', ''), 4000, 'context_note', empty=True)
        result['items'].append(row)
    return result


class State:
    """One process, identity, packet and role per exclusively locked directory."""
    def __init__(self, packet_path, state_dir, role):
        self.dirfd = None; self.lockfd = None; self.logfd = None
        try:
            require(role in ('reviewer', 'expert'), 'Invalid role')
            self.packet = load_packet(packet_path)
            self.role = role
            self.ids = {i['presentation_id'] for i in self.packet['items']}
            self.csrf = secrets.token_urlsafe(32)
            source = Path(packet_path).resolve(strict=True)
            directory = Path(os.path.abspath(state_dir))
            require(not source.is_relative_to(directory.resolve()), 'Packet cannot be inside state directory')
            # Reject symlinks in every existing output path component.
            for component in [directory, *directory.parents]:
                require(not component.is_symlink(), 'State directory cannot traverse symlinks')
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            source_stat = source.stat()
            for name in os.listdir(self.dirfd):
                st = os.stat(name, dir_fd=self.dirfd, follow_symlinks=False)
                require(not stat.S_ISLNK(st.st_mode), 'State children cannot be symlinks')
                require((st.st_dev, st.st_ino) != (source_stat.st_dev, source_stat.st_ino), 'Input/output collision')
            self.lockfd = self._open('session.lock', os.O_CREAT | os.O_RDWR)
            try:
                fcntl.flock(self.lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise ValueError('State directory is already locked') from e
            digest = hashlib.sha256(encode(self.packet)).hexdigest()
            self.meta = {'schema': 'evalops.label-session.v1', 'packet_sha256': digest,
                         'packet_id': self.packet['packet_id'], 'role': role, 'annotator': None}
            existing = self._read('session.json', 8192, missing=True)
            if existing is None:
                require(self._read('events.jsonl', MAX_LOG, missing=True) in (None, b''), 'Log without session metadata')
                self._write_meta()
            else:
                meta = strict_json(existing)
                require(isinstance(meta, dict) and set(meta) == set(self.meta), 'Corrupt session metadata')
                require(all(meta[k] == self.meta[k] for k in self.meta if k != 'annotator'), 'Packet or role mismatch')
                if meta['annotator'] is not None:
                    text(meta['annotator'], 100, 'annotator')
                self.meta = meta
            self.events = []; self.answers = {}; self.clients = {}; self.event_ids = set(); self.originals = {}
            raw = self._read('events.jsonl', MAX_LOG, missing=True) or b''
            require(not raw or raw.endswith(b'\n'), 'Truncated event log')
            for line in raw.splitlines():
                self._restore(strict_json(line))
            self.logfd = self._open('events.jsonl', os.O_CREAT | os.O_WRONLY | os.O_APPEND)
            os.fsync(self.dirfd)
        except Exception:
            self.close()
            raise

    def _open(self, name, flags):
        try:
            fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=self.dirfd)
        except OSError as e:
            raise ValueError('Cannot safely open state child') from e
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            os.close(fd)
            raise ValueError('State children must be regular files without hardlinks')
        return fd

    def _read(self, name, limit, missing=False):
        try:
            os.stat(name, dir_fd=self.dirfd, follow_symlinks=False)
        except FileNotFoundError:
            if missing: return None
            raise
        fd = self._open(name, os.O_RDONLY)
        with os.fdopen(fd, 'rb') as f:
            data = f.read(limit + 1)
        require(len(data) <= limit, 'State file too large')
        return data

    def _write_meta(self):
        name = 'session-' + secrets.token_hex(12) + '.tmp'
        fd = self._open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(encode(self.meta) + b'\n'); f.flush(); os.fsync(f.fileno())
            os.replace(name, 'session.json', src_dir_fd=self.dirfd, dst_dir_fd=self.dirfd)
            os.fsync(self.dirfd)
        finally:
            try: os.unlink(name, dir_fd=self.dirfd)
            except FileNotFoundError: pass

    def _payload(self, data, legacy=False):
        require(isinstance(data, dict), 'Expected decision object')
        pid = text(data.get('presentation_id'), 128, 'presentation_id')
        require(pid in self.ids, 'Unknown presentation')
        label = data.get('label')
        require(isinstance(label, str) and label in LABELS, 'Invalid label')
        payload = {'presentation_id': pid, 'label': label,
                'note': text(data.get('note', ''), 4000, 'note', empty=True),
                'client_id': text(data.get('client_id'), 128, 'client_id')}
        if legacy:
            return payload
        require(ANNOTATION_FIELDS <= set(data), 'Disposition and provenance are required')
        disposition = data['disposition']
        require(isinstance(disposition, str) and disposition in ('blocks', 'nonblocking', 'unknown'), 'Invalid disposition')
        action = data['affected_action']; reason = data['blocking_reason']
        if action is not None: action = text(action, 1024, 'affected_action')
        if reason is not None: reason = text(reason, 4000, 'blocking_reason')
        require(disposition == 'unknown' or action is not None, 'Known disposition requires affected action')
        require(disposition != 'blocks' or (label == 'defect' and reason is not None),
                'Blocking requires a defect and evidence/conditions')
        provenance = data['provenance']
        require(isinstance(provenance, dict) and set(provenance) == {
            'kind', 'exposure', 'attestation_ref', 'original_ref', 'protocol_version'}, 'Invalid provenance fields')
        kind = provenance['kind']; exposure = provenance['exposure']
        require(isinstance(kind, str) and kind in ('blind_human', 'user_assisted', 'post_review', 'independent_expert', 'unknown'), 'Invalid provenance kind')
        require(isinstance(exposure, str) and exposure in ('unexposed', 'exposed', 'unknown'), 'Invalid exposure')
        provenance = dict(provenance)
        for key in ('attestation_ref', 'original_ref'):
            if provenance[key] is not None: provenance[key] = text(provenance[key], 1024, key)
        provenance['protocol_version'] = text(provenance['protocol_version'], 128, 'protocol_version')
        require(kind not in ('blind_human', 'independent_expert') or exposure == 'unexposed',
                'Independent/blind annotation requires unexposed attestation')
        require(kind not in ('user_assisted', 'post_review') or exposure != 'unexposed',
                'Assisted/post-review annotation cannot attest unexposed')
        require(kind != 'independent_expert' or provenance['attestation_ref'] is not None,
                'Independent expert requires an attestation reference')
        payload.update(disposition=disposition, affected_action=action, blocking_reason=reason, provenance=provenance)
        return payload

    def _restore(self, event):
        require(isinstance(event, dict), 'Corrupt event')
        legacy = 'annotation_schema' not in event
        payload = self._payload(event, legacy=legacy)
        keys = set(payload) | {'event_id', 'role', 'annotator', 'packet_id', 'rubric_version', 'labeled_at', 'label_source', 'supersedes'}
        if not legacy:
            keys |= {'annotation_schema', 'original_event_id'}
            require(event['annotation_schema'] == ANNOTATION_SCHEMA, 'Invalid annotation schema')
        require(set(event) == keys, 'Corrupt event fields')
        require(self.meta['annotator'] is not None and event['annotator'] == self.meta['annotator'], 'Event identity mismatch')
        require(event['role'] == self.role and event['packet_id'] == self.packet['packet_id'] and event['rubric_version'] == self.packet['rubric_version'] and event['label_source'] == 'human', 'Event provenance mismatch')
        try:
            require(str(uuid.UUID(event['event_id'])) == event['event_id'], 'Invalid event ID')
            require(event['labeled_at'].endswith('Z'), 'Invalid event timestamp')
            datetime.datetime.fromisoformat(event['labeled_at'].replace('Z', '+00:00'))
        except (TypeError, AttributeError) as e:
            raise ValueError('Corrupt event ID or timestamp') from e
        require(event['event_id'] not in self.event_ids, 'Duplicate event ID')
        require(payload['client_id'] not in self.clients, 'Duplicate client ID in log')
        previous = self.answers.get(payload['presentation_id'])
        require(event['supersedes'] == (previous['event_id'] if previous else None), 'Broken correction history')
        original = self.originals.get(payload['presentation_id'], event['event_id'])
        if not legacy:
            require(event['original_event_id'] == original, 'Broken original event reference')
        require(len(self.events) < 50000, 'Event limit reached')
        self.events.append(event); self.event_ids.add(event['event_id'])
        self.answers[payload['presentation_id']] = event
        self.originals[payload['presentation_id']] = original
        self.clients[payload['client_id']] = (payload, event)

    def _available(self):
        if self.logfd is None:
            raise OSError('Session storage is closed; restart required')

    def start(self, data):
        self._available()
        require(isinstance(data, dict), 'Expected identity object')
        name = text(data.get('annotator'), 100, 'annotator').strip()
        require(self.meta['annotator'] in (None, name), 'Identity is already bound; use a separate state directory')
        self.meta['annotator'] = name
        try:
            self._write_meta()
        except OSError:
            self.close()
            raise
        return self.snapshot()

    def decide(self, data):
        self._available()
        require(self.meta['annotator'] is not None, 'Enter your name before labeling')
        # Old clients can acknowledge an exact retry of a legacy event, but
        # cannot create another annotation without the new structured fields.
        require(isinstance(data, dict), 'Expected decision object')
        client = text(data.get('client_id'), 128, 'client_id')
        prior = self.clients.get(client)
        legacy_retry = (prior is not None and 'annotation_schema' not in prior[1]
                        and not (ANNOTATION_FIELDS & set(data)))
        payload = self._payload(data, legacy=legacy_retry)
        prior = self.clients.get(payload['client_id'])
        if prior:
            require(prior[0] == payload, 'Conflicting retry ID')
            return prior[1]
        previous = self.answers.get(payload['presentation_id'])
        event = dict(payload, event_id=str(uuid.uuid4()), role=self.role,
                     annotator=self.meta['annotator'], packet_id=self.packet['packet_id'],
                     rubric_version=self.packet['rubric_version'], label_source='human',
                     labeled_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
                     supersedes=previous['event_id'] if previous else None)
        event['annotation_schema'] = ANNOTATION_SCHEMA
        event['original_event_id'] = self.originals.get(payload['presentation_id'], event['event_id'])
        raw = encode(event) + b'\n'
        require(len(self.events) < 50000 and os.fstat(self.logfd).st_size + len(raw) <= MAX_LOG, 'Event log full')
        # An I/O failure is fatal: never continue appending after a partial write.
        try:
            written = 0
            while written < len(raw):
                n = os.write(self.logfd, raw[written:])
                if n <= 0: raise OSError('Short write')
                written += n
            os.fsync(self.logfd)
        except OSError:
            self.close()
            raise
        self._restore(event)
        return event

    def snapshot(self):
        self._available()
        return {'packet': self.packet, 'role': self.role, 'annotator': self.meta['annotator'],
                'answers': {pid: self._project(e) for pid, e in self.answers.items()},
                'progress': {'answered': len(self.answers), 'total': len(self.ids)},
                'csrf_token': self.csrf}

    def _project(self, event):
        if 'annotation_schema' in event:
            return event
        # Enrich only the view. Original journal bytes and votes stay intact.
        return dict(event, annotation_schema='evalops.annotation.legacy',
                    disposition='unknown', affected_action=None, blocking_reason=None,
                    original_event_id=self.originals[event['presentation_id']],
                    provenance={'kind': 'legacy_unknown', 'exposure': 'unknown',
                                'attestation_ref': None, 'original_ref': None, 'protocol_version': None})

    def export(self):
        self._available()
        return ''.join(encode(self._project(e)).decode() + '\n' for e in self.events)

    def close(self):
        for key in ['logfd', 'lockfd', 'dirfd']:
            fd = getattr(self, key, None)
            if fd is not None:
                os.close(fd); setattr(self, key, None)


def make_server(state, port=0):
    class Handler(http.server.BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(3)
            super().setup()

        def log_message(self, *_):
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8', download=False):
            if not isinstance(body, bytes): body = encode(body)
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
            if download: self.send_header('Content-Disposition', 'attachment; filename="my-judgments.jsonl"')
            self.end_headers(); self.wfile.write(body)

        def allowed_host(self):
            port = self.server.server_address[1]
            hosts = self.headers.get_all('Host', [])
            return len(hosts) == 1 and hosts[0] in (f'127.0.0.1:{port}', f'localhost:{port}')

        def do_GET(self):
            if not self.allowed_host(): return self.send(403, {'error': 'Localhost Host required'})
            try:
                if self.path == '/api/session': return self.send(200, state.snapshot())
                if self.path == '/api/export': return self.send(200, state.export().encode(), 'application/x-ndjson; charset=utf-8', True)
            except OSError:
                return self.send(503, {'error': 'Storage unavailable; stop and restart the tool.'})
            if self.path in ASSETS:
                name, mime = ASSETS[self.path]
                return self.send(200, (Path(__file__).parent / 'label-ui' / name).read_bytes(), mime)
            self.send(404, {'error': 'Not found'})

        def do_POST(self):
            origin = 'http://' + self.headers.get('Host', '')
            if (not self.allowed_host() or self.headers.get_all('Origin', []) != [origin]
                    or self.headers.get_all('X-CSRF-Token', []) != [state.csrf]
                    or self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('same-origin', 'none')):
                return self.send(403, {'error': 'Same-origin request and CSRF token required'})
            if self.path not in ('/api/session', '/api/decision'): return self.send(404, {'error': 'Not found'})
            try:
                require(self.headers.get('Content-Type', '').split(';')[0] == 'application/json', 'JSON required')
                require(len(self.headers.get_all('Content-Length', [])) == 1 and not self.headers.get('Transfer-Encoding'), 'Content length required')
                length = int(self.headers['Content-Length'])
                require(0 < length <= 32768, 'Request too large or empty')
                self.connection.settimeout(3)
                raw = self.rfile.read(length)
                require(len(raw) == length, 'Incomplete request')
                data = strict_json(raw)
                result = state.start(data) if self.path == '/api/session' else state.decide(data)
                self.send(200, result)
            except (ValueError, TypeError):
                self.send(400, {'error': 'Invalid request, identity, decision, or conflicting retry. Check fields and session.'})
            except OSError:
                self.send(503, {'error': 'Storage unavailable. Stop and restart the tool; retain this draft.'})

    # Serial request handling and the process lock keep all writes ordered.
    server = http.server.HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 3
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Private loopback human finding review. Resume with the same packet, role and state directory. Use a separate packet AND state directory for an independent expert.')
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help='Start or resume a local browser review; enter your name in the browser')
    serve.add_argument('--packet', required=True, type=Path, help='Frozen public packet JSON; never a private mapping')
    serve.add_argument('--state-dir', required=True, type=Path, help='Exclusive private session directory; separate per human/role')
    serve.add_argument('--role', choices=['reviewer', 'expert'], required=True)
    serve.add_argument('--port', type=int, default=8765, help='Loopback port (0 prints an available port)')
    args = parser.parse_args(argv)
    state = None; server = None
    try:
        require(0 <= args.port <= 65535, 'Invalid port')
        state = State(args.packet, args.state_dir, args.role)
        server = make_server(state, args.port)
        print(f'http://127.0.0.1:{server.server_address[1]}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError) as e:
        print(json.dumps({'error': str(e)}), file=sys.stderr)
        return 2
    finally:
        if server: server.server_close()
        if state: state.close()


if __name__ == '__main__':
    sys.exit(main())
