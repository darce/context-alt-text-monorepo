#!/usr/bin/env bash
# E15-29 Slice 0: assert the demo Caddy vhost serves the sslip.io interim host
# alongside demo.altcontext.com, both routing to the demo-wp upstream.
#
# Structural check only — the authoritative `caddy validate` runs at deploy time
# inside scripts/deploy/sync-demo.sh (the VM has no host caddy binary either).
#
# Usage: bash infra/oci/demo/tests/verify-demo-caddy-interim.sh
set -euo pipefail

CADDYFILE="${CADDYFILE:-apps/prototype-description-service/Caddyfile}"
INTERIM_HOST='129-213-40-111.sslip.io'

if [[ ! -f "$CADDYFILE" ]]; then
  echo "FAIL: Caddyfile not found at $CADDYFILE" >&2
  exit 2
fi

fail=0
check() { # <regex> <human description>
  if ! grep -qE "$1" "$CADDYFILE"; then
    echo "FAIL: missing — $2" >&2
    fail=1
  fi
}

check "$INTERIM_HOST" "sslip.io interim host ($INTERIM_HOST) in the demo vhost"
check 'demo\.altcontext\.com' "demo.altcontext.com target host (kept for when operator DNS lands)"
check 'reverse_proxy demo-wp:80' "demo-wp:80 upstream"
check 'path /xmlrpc\.php' "xmlrpc 403 hardening preserved"

# Demo root must land on the walkthrough, not an intermediate homepage. The
# redirect has to stay narrowly scoped: bare root only, safe methods only.
check '@demo_root' "@demo_root named matcher for the demo-root redirect"
check 'redir @demo_root /guide/ 302' "302 redirect from the demo root to /guide/"
check '^[[:space:]]*path /$' "demo-root matcher scoped to the exact bare root (path /, not path /*)"
check '^[[:space:]]*method GET HEAD$' "demo-root matcher restricted to GET and HEAD"
check '^[[:space:]]*host demo\.altcontext\.com$' "demo-root redirect scoped to the public demo hostname"

# Every vhost that exists on the live proxy must exist here. sync-demo.sh
# promotes this file over /opt/acx-backend/Caddyfile wholesale, so a vhost that
# lives only on the VM is deleted by the next deploy (GUIDEDEPLOY-1-BR-03).
check '^dl\.darce\.xyz \{' "dl.darce.xyz vhost (live-only vhosts are destroyed by the next promote)"

# A doubled slash must never reach a published link.
if grep -qF '//guide' "$CADDYFILE"; then
  echo "FAIL: '//guide' appears in $CADDYFILE — published links must use a single leading slash" >&2
  fail=1
fi

# The two demo hosts must share ONE site block (comma-separated addresses), not
# two blocks — a second block would duplicate the upstream and the xmlrpc guard.
if ! grep -qE "demo\.altcontext\.com, *${INTERIM_HOST} *\{|${INTERIM_HOST}, *demo\.altcontext\.com *\{" "$CADDYFILE"; then
  echo "FAIL: demo.altcontext.com and $INTERIM_HOST must be comma-separated addresses on one site block" >&2
  fail=1
fi

# Brace balance sanity (cheap structural guard short of caddy validate).
opens=$(grep -o '{' "$CADDYFILE" | wc -l | tr -d ' ')
closes=$(grep -o '}' "$CADDYFILE" | wc -l | tr -d ' ')
if [[ "$opens" != "$closes" ]]; then
  echo "FAIL: brace imbalance — $opens '{' vs $closes '}'" >&2
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  echo "verify-demo-caddy-interim: FAIL" >&2
  exit 1
fi
echo "verify-demo-caddy-interim: OK — demo vhost serves $INTERIM_HOST + demo.altcontext.com -> demo-wp:80; bare root 302 -> /guide/"
