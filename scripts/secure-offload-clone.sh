#!/usr/bin/env bash
# Secure offload sandbox — shallow, secret-scanned clone for UNTRUSTED-backend
# offload lanes (grok-cli in particular).
#
# THREAT: the grok Build CLI uploads the full .git object database to
# gs://grok-code-session-traces regardless of the privacy opt-out
# ("xAI Grok CLI Uploads Full Repos and Secrets, Opt-Out Ignored"). A normal
# git worktree SHARES the primary .git, so the entire history — including any
# secret ever committed-then-deleted — is bundleable and exfiltratable.
#
# CONTROL (git layer): a `--depth=1 --no-local` clone gives the offload CLI ONLY
# the current HEAD tree — no historical objects to bundle. The worst it can ship
# is the source you already let it edit. A secret scan of that tip confirms no
# LIVE committed secret is present. This is defense-in-depth with the primary
# control (network egress-deny of the /v1/storage upload host) — see
# infra/oci/INFRA-TOPOLOGY.md / the secure-offload runbook.
#
# Usage:
#   scripts/secure-offload-clone.sh --primary ROOT --dest PATH [--branch BR]
#                                   [--scanner auto|gitleaks|builtin|none]
# Prints the sandbox path on success; exits non-zero (and removes a partial
# sandbox) if the HEAD tree fails the secret scan.
set -euo pipefail

primary="" ; dest="" ; branch="secure-offload" ; scanner="auto"
die(){ echo "secure-offload-clone: $*" >&2; exit 2; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --primary) primary="$2"; shift 2 ;;
    --dest) dest="$2"; shift 2 ;;
    --branch) branch="$2"; shift 2 ;;
    --scanner) scanner="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown arg: $1" ;;
  esac
done
[ -n "$primary" ] || die "--primary is required"
[ -n "$dest" ] || die "--dest is required"
primary="$(cd "$primary" && pwd)"
[ -e "$dest" ] && die "dest already exists: $dest"

# Any exit before the success path must not leave a partial/unscanned sandbox
# behind (cleared just before the final success echo).
trap 'rm -rf "$dest"' EXIT

# 1. Shallow, non-local clone: only HEAD tree, no historical objects to bundle.
#    file:// + --no-local disables git's local hardlink/altobjects optimization
#    (a plain local clone would share objects → full history present).
git clone --quiet --no-local --depth=1 "file://$primary" "$dest" \
  || die "shallow clone failed"
git -C "$dest" switch -c "$branch" >/dev/null 2>&1 || git -C "$dest" checkout -b "$branch" >/dev/null 2>&1 || true
# 2. Remove the origin remote — hygiene only, NOT a security boundary: a local
#    `git fetch file://<primary>` from inside the sandbox can re-acquire history
#    regardless. The real defenses are the shallow object set (no historical
#    objects present to bundle) and the network egress deny
#    (infra/security/grok-egress-deny.md); origin removal just avoids accidental
#    fetches by well-behaved tooling.
git -C "$dest" remote remove origin >/dev/null 2>&1 || true
# 3. Mark it so the lane-close path rm -rf's it instead of `git worktree remove`.
#    Locally excluded so the marker itself never makes the sandbox read as dirty.
: > "$dest/.acx-secure-offload"
echo '.acx-secure-offload' >> "$dest/.git/info/exclude"

# 4. Secret-scan the HEAD tree (tracked files only). Fail closed BOTH on a live
#    secret and on scan-tool errors — a broken scanner must never pass the gate.
scan_builtin(){
  # High-signal LIVE-secret patterns only (OCIDs are identifiers, not secrets — skip).
  # macOS/BSD git grep is POSIX ERE: no (?i) inline flag (invalid, exits 128), and
  # every pattern must follow -e so a leading dash is never parsed as an option.
  # Pass 1 (case-sensitive): known live-key formats.
  local key_patterns='-----BEGIN [A-Z ]*PRIVATE KEY-----|AKIA[0-9A-Z]{16}|xai-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{20,}|gh[ps]_[A-Za-z0-9]{36}|AIza[0-9A-Za-z_-]{35}'
  # Pass 2 (case-insensitive): generic credential assignment. Quoted, digit-bearing
  # values only — identifiers/placeholders (your_api_key_here) have no digits, so
  # this stays high-signal without excluding docs or tests.
  local assign_patterns='(api[_-]?key|secret|token|password|passwd)[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9/+_.=-]{3,}[0-9][A-Za-z0-9/+_.=-]{7,}["'"'"']'
  # Scan everything tracked — including *.md and env files (a live secret in a doc
  # or committed env file is still a live secret). Exclude only lockfiles, test
  # fixtures, and *.example placeholder templates (sample values by contract).
  local rc
  rc=0
  git -C "$dest" grep -nIE -e "$key_patterns" -- \
    ':!*.lock' ':!*/fixtures/*' ':!*.example' >&2 || rc=$?
  [ "$rc" -eq 0 ] && return 1
  [ "$rc" -eq 1 ] || die "builtin secret scan errored (git grep exit $rc) — failing closed"
  rc=0
  git -C "$dest" grep -inIE -e "$assign_patterns" -- \
    ':!*.lock' ':!*/fixtures/*' ':!*.example' >&2 || rc=$?
  [ "$rc" -eq 0 ] && return 1
  [ "$rc" -eq 1 ] || die "builtin secret scan errored (git grep exit $rc) — failing closed"
  return 0
}
run_scan(){
  case "$scanner" in
    none) echo "secure-offload-clone: scan SKIPPED (--scanner none)" >&2; return 0 ;;
    gitleaks) command -v gitleaks >/dev/null || die "gitleaks requested but not installed" ;;
    builtin) : ;;
    auto) command -v gitleaks >/dev/null && scanner=gitleaks || scanner=builtin ;;
  esac
  if [ "$scanner" = "gitleaks" ]; then
    gitleaks detect --source "$dest" --no-git --redact --exit-code 1 >&2 || return 1
  else
    scan_builtin || return 1
  fi
  return 0
}
if ! run_scan; then
  # EXIT trap removes the sandbox.
  die "SECRET SCAN FAILED — live secret in HEAD tree; sandbox removed. Purge the secret from the current commit before offloading."
fi

trap - EXIT
echo "$dest"
