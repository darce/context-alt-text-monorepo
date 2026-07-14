#!/usr/bin/env python3
"""Grok egress-deny + logging proxy (allowlist CONNECT proxy).

The grok Build CLI uploads the full .git bundle to gs://grok-code-session-traces
(storage.googleapis.com, via /upload/storage) regardless of any opt-out. Inference
goes to a DIFFERENT host (api.x.ai / cli-chat-proxy.grok.com / grok.com), so the
exfil is separable at the network layer.

This is an allowlist HTTPS CONNECT proxy: only inference/auth hosts may be reached;
the Google upload hosts (and anything else) are DENIED and LOGGED. It is:
  - grok-scoped   — only traffic that uses this proxy is affected (not the whole box)
  - host-agnostic — run it on the laptop (where offload runs today) or an OCI VM
  - the test rig  — the egress log is exactly the evidence the hold-lift test needs

Usage:
  python3 scripts/grok-egress-proxy.py --port 8899 --log egress.log &
  HTTPS_PROXY=http://127.0.0.1:8899 HTTP_PROXY=http://127.0.0.1:8899 \
      NO_PROXY= grok "your task"
  # An ALLOW line for api.x.ai + zero EXFIL-BLOCKED lines and a working session
  # => inference works and the bundle upload was denied.
"""
from __future__ import annotations
import argparse, datetime, re, select, socket, threading

# Inference / auth / model-list hosts grok legitimately needs (allowlist).
ALLOW_PATTERNS = [
    r"(^|\.)x\.ai$",
    r"(^|\.)grok\.com$",
]
# Known exfil hosts — denied like everything else, but tagged for clear logging.
EXFIL_PATTERNS = [r"googleapis\.com$"]

_allow_re = [re.compile(p, re.I) for p in ALLOW_PATTERNS]
_exfil_re = [re.compile(p, re.I) for p in EXFIL_PATTERNS]


def classify(host: str) -> str:
    if any(r.search(host) for r in _allow_re):
        return "ALLOW"
    if any(r.search(host) for r in _exfil_re):
        return "EXFIL-BLOCKED"
    return "DENIED"


class Proxy:
    def __init__(self, port: int, logf):
        self.port = port
        self.logf = logf

    def log(self, *parts):
        line = " ".join([datetime.datetime.now().isoformat(timespec="seconds"), *map(str, parts)])
        print(line, flush=True)
        if self.logf:
            self.logf.write(line + "\n"); self.logf.flush()

    def serve(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", self.port))
        s.listen(64)
        self.log("PROXY-UP", f"127.0.0.1:{self.port}", "allow=" + ",".join(ALLOW_PATTERNS))
        while True:
            client, _ = s.accept()
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket):
        try:
            client.settimeout(15)
            data = client.recv(65536)
            line = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
            m = re.match(r"CONNECT\s+([^:\s]+):(\d+)", line)
            if not m:
                # This proxy only brokers HTTPS (CONNECT). Plain HTTP is refused.
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n"); return
            host, port = m.group(1), int(m.group(2))
            verdict = classify(host)
            self.log(verdict, host, port)
            if verdict != "ALLOW":
                client.sendall(b"HTTP/1.1 403 Forbidden (acx grok egress-deny)\r\n\r\n"); return
            try:
                upstream = socket.create_connection((host, port), timeout=15)
            except OSError as e:
                self.log("UPSTREAM-FAIL", host, port, str(e))
                client.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n"); return
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            self._pump(client, upstream)
        except Exception as e:  # noqa: BLE001 - best-effort broker
            try:
                self.log("ERROR", str(e))
            finally:
                pass
        finally:
            client.close()

    @staticmethod
    def _pump(a: socket.socket, b: socket.socket):
        a.settimeout(None); b.settimeout(None)
        socks = [a, b]
        try:
            while True:
                r, _, x = select.select(socks, [], socks, 60)
                if x or not r:
                    break
                for s in r:
                    other = b if s is a else a
                    buf = s.recv(65536)
                    if not buf:
                        return
                    other.sendall(buf)
        except OSError:
            return
        finally:
            b.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8899)
    ap.add_argument("--log", default=None, help="append egress decisions to this file")
    args = ap.parse_args()
    logf = open(args.log, "a") if args.log else None
    Proxy(args.port, logf).serve()


if __name__ == "__main__":
    main()
