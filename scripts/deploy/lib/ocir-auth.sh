#!/usr/bin/env bash
# OCIR docker-login credential resolution via OCI Vault (OCIRV-1).
#
# The token lives in acx-vault and reaches Docker on stdin. Docker is given a
# private, short-lived DOCKER_CONFIG directory, so any credential material it
# writes while authenticating is removed on every snippet exit path. The token
# is never placed in a process argument.
#
# Sourced by scripts/deploy/recognition-service.sh and the rotation helper.
# Keep this compatible with macOS bash 3.2 and the VM's bash.

# acx-vault (root compartment, us-ashburn-1). An OCID is not a secret.
ACX_VAULT_OCID="${ACX_VAULT_OCID:-ocid1.vault.oc1.iad.ejvffpzlaafc4.abuwcljr3j4chidobdkiqx6igrzb4p3wffl43bjelxzfghkehdpuzle7cjla}"
ACX_OCIR_TOKEN_SECRET="${ACX_OCIR_TOKEN_SECRET:-OCIR_AUTH_TOKEN}"
ACX_OCIR_USERNAME_SECRET="${ACX_OCIR_USERNAME_SECRET:-OCIR_USERNAME}"
ACX_OCIR_GENERATION_SECRET="${ACX_OCIR_GENERATION_SECRET:-OCIR_CREDENTIAL_GENERATION}"
ACX_REMOTE_OCI_BIN="${ACX_REMOTE_OCI_BIN:-\$HOME/.oci-venv/bin/oci}"
ACX_LOCAL_OCI_BIN="${ACX_LOCAL_OCI_BIN:-oci}"
ACX_VAULT_FETCH_TIMEOUT="${ACX_VAULT_FETCH_TIMEOUT:-30}"

# Classification values are centralized so producers and hint consumers cannot
# silently drift onto different spellings.
ACX_OCIR_FAILURE_OCI_CLI_MISSING=oci_cli_missing
ACX_OCIR_FAILURE_DOCKER_CLI_MISSING=docker_cli_missing
ACX_OCIR_FAILURE_SECRET_MISSING=secret_missing
ACX_OCIR_FAILURE_VAULT_DENIED=vault_denied
ACX_OCIR_FAILURE_VAULT_UNREACHABLE=vault_unreachable
ACX_OCIR_FAILURE_VAULT_REQUEST=vault_request_failed
ACX_OCIR_FAILURE_OCIR_UNREACHABLE=ocir_unreachable
ACX_OCIR_FAILURE_OCIR_REJECTED=ocir_rejected
ACX_OCIR_FAILURE_CREDENTIAL_INCONSISTENT=credential_inconsistent
ACX_OCIR_FAILURE_SSH=ssh_failed
ACX_OCIR_FAILURE_UNKNOWN=unknown

ocir_validate_fetch_timeout() {
  case "${ACX_VAULT_FETCH_TIMEOUT}" in
    ''|*[!0-9]*)
      printf 'ACX_VAULT_FETCH_TIMEOUT must be a positive integer (got %s)\n' \
        "${ACX_VAULT_FETCH_TIMEOUT}" >&2
      return 2 ;;
    *[1-9]*) return 0 ;;
    *)
      printf 'ACX_VAULT_FETCH_TIMEOUT must be a positive integer (got %s)\n' \
        "${ACX_VAULT_FETCH_TIMEOUT}" >&2
      return 2 ;;
  esac
}

# Emit one data assignment using bash's shell quoting. Values are assigned once
# and every use in the executable snippet is a quoted variable expansion. This
# keeps command substitutions and metacharacters in overrides inert on both the
# local `bash -c` and remote `bash -s` execution paths.
ocir_emit_assignment() {
  printf '%s=' "$1"
  printf '%q' "$2"
  printf '\n'
}

# Emit the OCI invocation used inside a generated login program. The arguments
# are variable references rather than interpolated caller-controlled text.
ocir_vault_fetch_snippet() {
  printf 'acx_bounded vault "$ACX_OCIR_OCI_BIN" --auth "$ACX_OCIR_AUTH_MODE" secrets secret-bundle get-secret-bundle-by-name --vault-id "$ACX_VAULT_OCID" --secret-name "$ACX_OCIR_SECRET_NAME" --query '\''data."secret-bundle-content".content'\'' --raw-output | base64 -d | acx_require_nonempty'
}

# Emit a fetch-and-login program for one host.
# $1 = oci binary, $2 = --auth mode, $3 = registry.
ocir_login_snippet() {
  ocir__bin="$1"
  ocir__auth="$2"
  ocir__registry="$3"

  ocir_validate_fetch_timeout || return

  printf 'set -euo pipefail\n'
  ocir_emit_assignment ACX_OCIR_OCI_BIN "${ocir__bin}"
  ocir_emit_assignment ACX_OCIR_AUTH_MODE "${ocir__auth}"
  ocir_emit_assignment ACX_OCIR_REGISTRY "${ocir__registry}"
  ocir_emit_assignment ACX_VAULT_OCID "${ACX_VAULT_OCID}"
  ocir_emit_assignment ACX_OCIR_USERNAME_SECRET "${ACX_OCIR_USERNAME_SECRET}"
  ocir_emit_assignment ACX_OCIR_TOKEN_SECRET "${ACX_OCIR_TOKEN_SECRET}"
  ocir_emit_assignment ACX_OCIR_GENERATION_SECRET "${ACX_OCIR_GENERATION_SECRET}"
  ocir_emit_assignment ACX_VAULT_FETCH_TIMEOUT "${ACX_VAULT_FETCH_TIMEOUT}"
  ocir_emit_assignment ACX_OCIR_DOCKER_CONFIG_DIR "${ACX_OCIR_DOCKER_CONFIG_DIR:-}"
  printf '%s\n' \
    'case "$ACX_OCIR_OCI_BIN" in '\''$HOME/'\''*) ACX_OCIR_OCI_BIN="${HOME}/${ACX_OCIR_OCI_BIN#\$HOME/}" ;; esac' \
    'umask 077' \
    'acx_owns_docker_config=0' \
    'if [ -n "$ACX_OCIR_DOCKER_CONFIG_DIR" ]; then' \
    '  ACX_OCIR_DOCKER_CONFIG="$ACX_OCIR_DOCKER_CONFIG_DIR"' \
    '  [ -d "$ACX_OCIR_DOCKER_CONFIG" ] || mkdir -p -- "$ACX_OCIR_DOCKER_CONFIG"' \
    '  chmod 700 "$ACX_OCIR_DOCKER_CONFIG"' \
    'else' \
    '  ACX_OCIR_DOCKER_CONFIG="$(mktemp -d "${TMPDIR:-/tmp}/acx-ocir-docker.XXXXXX")"' \
    '  acx_owns_docker_config=1' \
    'fi' \
    'export DOCKER_CONFIG="$ACX_OCIR_DOCKER_CONFIG"' \
    'acx_active_pid=' \
    'acx_cleanup() {' \
    '  if [ -n "${acx_active_pid:-}" ]; then kill "$acx_active_pid" 2>/dev/null || true; wait "$acx_active_pid" 2>/dev/null || true; fi' \
    '  if [ "$acx_owns_docker_config" -eq 1 ]; then rm -rf -- "$ACX_OCIR_DOCKER_CONFIG"; fi' \
    '}' \
    'trap acx_cleanup EXIT' \
    'trap '\''exit 129'\'' HUP' \
    'trap '\''exit 130'\'' INT' \
    'trap '\''exit 143'\'' TERM' \
    'acx_bounded() {' \
    '  acx_label="$1"; shift' \
    '  exec 3<&0' \
    '  "$@" <&3 &' \
    '  acx_active_pid=$!' \
    '  exec 3<&-' \
    '  acx_started=$SECONDS' \
    '  while kill -0 "$acx_active_pid" 2>/dev/null; do' \
    '    if [ $((SECONDS - acx_started)) -ge "$ACX_VAULT_FETCH_TIMEOUT" ]; then' \
    '      kill "$acx_active_pid" 2>/dev/null || true' \
    '      sleep 0.1' \
    '      kill -9 "$acx_active_pid" 2>/dev/null || true' \
    '      wait "$acx_active_pid" 2>/dev/null || true' \
    '      acx_active_pid=' \
    '      printf '\''acx-timeout:%s after %ss\n'\'' "$acx_label" "$ACX_VAULT_FETCH_TIMEOUT" >&2' \
    '      return 124' \
    '    fi' \
    '    sleep 0.05' \
    '  done' \
    '  if wait "$acx_active_pid"; then acx_rc=0; else acx_rc=$?; fi' \
    '  acx_active_pid=' \
    '  if [ "$acx_rc" -eq 127 ]; then printf '\''acx-command-missing:%s\n'\'' "$acx_label" >&2; fi' \
    '  return "$acx_rc"' \
    '}' \
    'acx_require_nonempty() {' \
    '  awk '\''BEGIN { ORS="" } { seen=1; print } END { if (!seen) { print "Vault secret was empty" > "/dev/stderr"; exit 65 } }'\''' \
    '}'

  printf 'ACX_OCIR_SECRET_NAME="$ACX_OCIR_GENERATION_SECRET"\n'
  printf 'acx_ocir_first="$(%s)"\n' "$(ocir_vault_fetch_snippet)"
  printf '%s\n' \
    'case "$acx_ocir_first" in' \
    '  STABLE:*)' \
    '    acx_ocir_generation_before="$acx_ocir_first"' \
    '    acx_ocir_generation_mode=versioned' \
    '    ACX_OCIR_SECRET_NAME="$ACX_OCIR_USERNAME_SECRET"'
  printf '    acx_ocir_user="$(%s)"\n' "$(ocir_vault_fetch_snippet)"
  printf '%s\n' \
    '    ;;' \
    '  UPDATING:*) printf '\''acx-credential-generation:updating\n'\'' >&2; exit 76 ;;' \
    '  *)' \
    '    # One-release migration path for pre-generation Vault fixtures.' \
    '    acx_ocir_generation_mode=legacy' \
    '    acx_ocir_user="$acx_ocir_first"' \
    '    ;;' \
    'esac'
  printf '%s\n' '[ -n "$acx_ocir_user" ] || { printf '\''OCIR username secret was empty\n'\'' >&2; exit 65; }'
  printf '%s\n' 'printf '\''acx-vault-read-ok\n'\'' >&2'
  printf 'ACX_OCIR_SECRET_NAME="$ACX_OCIR_TOKEN_SECRET"\n'
  printf 'set +x\n'
  printf 'acx_ocir_token="$(%s)"\n' "$(ocir_vault_fetch_snippet)"
  printf '%s\n' \
    'if [ "$acx_ocir_generation_mode" = versioned ]; then' \
    '  ACX_OCIR_SECRET_NAME="$ACX_OCIR_GENERATION_SECRET"'
  printf '  acx_ocir_generation_after="$(%s)"\n' "$(ocir_vault_fetch_snippet)"
  printf '%s\n' \
    '  [ "$acx_ocir_generation_before" = "$acx_ocir_generation_after" ] || { printf '\''acx-credential-generation:changed\n'\'' >&2; exit 76; }' \
    '  case "$acx_ocir_generation_after" in STABLE:*) ;; *) printf '\''acx-credential-generation:updating\n'\'' >&2; exit 76 ;; esac' \
    'fi'
  printf 'acx_ocir_login_stderr="$DOCKER_CONFIG/login.stderr"\n'
  printf 'set +e\n'
  printf 'printf '\''%%s'\'' "$acx_ocir_token" | acx_bounded ocir docker login "$ACX_OCIR_REGISTRY" -u "$acx_ocir_user" --password-stdin >/dev/null 2>"$acx_ocir_login_stderr"\n'
  printf '%s\n' \
    'acx_ocir_login_rc=$?' \
    'set -e' \
    'if [ "$acx_ocir_login_rc" -ne 0 ]; then' \
    '  acx_ocir_captured="$(cat "$acx_ocir_login_stderr")"' \
    '  case "$acx_ocir_captured" in' \
    '    *acx-timeout:ocir*) printf '\''acx-timeout:ocir (credential-bearing stderr suppressed)\n'\'' >&2; exit "$acx_ocir_login_rc" ;;' \
    '    *[Uu]nauthorized*|*401*|*"authentication required"*) acx_ocir_safe_class=ocir_rejected ;;' \
    '    *"timed out"*|*"Cannot connect"*|*"Connection refused"*) acx_ocir_safe_class=ocir_unreachable ;;' \
    '    *"command not found"*|*"No such file or directory"*) acx_ocir_safe_class=docker_cli_missing ;;' \
    '    *) acx_ocir_safe_class=unknown ;;' \
    '  esac' \
    '  printf '\''acx-safe-login-error:%s (credential-bearing stderr suppressed)\n'\'' "$acx_ocir_safe_class" >&2' \
    '  exit "$acx_ocir_login_rc"' \
    'fi'
}

# Classify combined stderr from the generated program.
ocir_classify_login_failure() {
  case "$1" in
    *acx-safe-login-error:docker_cli_missing*)
      printf '%s' "$ACX_OCIR_FAILURE_DOCKER_CLI_MISSING" ;;
    *acx-safe-login-error:ocir_unreachable*)
      printf '%s' "$ACX_OCIR_FAILURE_OCIR_UNREACHABLE" ;;
    *acx-safe-login-error:ocir_rejected*)
      printf '%s' "$ACX_OCIR_FAILURE_OCIR_REJECTED" ;;
    *acx-credential-generation:*)
      printf '%s' "$ACX_OCIR_FAILURE_CREDENTIAL_INCONSISTENT" ;;
    *acx-command-missing:ocir*|*"docker: command not found"*|*"docker: No such file or directory"*)
      printf '%s' "$ACX_OCIR_FAILURE_DOCKER_CLI_MISSING" ;;
    *acx-command-missing:vault*|*"oci: command not found"*|*"/oci: No such file or directory"*|*" oci: No such file or directory"*)
      printf '%s' "$ACX_OCIR_FAILURE_OCI_CLI_MISSING" ;;
    *"ssh:"*"No such file or directory"*)
      printf '%s' "$ACX_OCIR_FAILURE_SSH" ;;
    *acx-timeout:ocir*)
      printf '%s' "$ACX_OCIR_FAILURE_OCIR_UNREACHABLE" ;;
    *acx-timeout:vault*)
      printf '%s' "$ACX_OCIR_FAILURE_VAULT_UNREACHABLE" ;;
    *NotAuthorizedOrNotFound*)
      case "$1" in
        *acx-vault-read-ok*) printf '%s' "$ACX_OCIR_FAILURE_SECRET_MISSING" ;;
        *) printf '%s' "$ACX_OCIR_FAILURE_VAULT_DENIED" ;;
      esac ;;
    *"secret was empty"*)
      printf '%s' "$ACX_OCIR_FAILURE_SECRET_MISSING" ;;
    *NotAuthenticated*|*"not authorized"*|*'"status": 401'*|*'"status": 403'*)
      printf '%s' "$ACX_OCIR_FAILURE_VAULT_DENIED" ;;
    *"OCIR"*"timed out"*)
      printf '%s' "$ACX_OCIR_FAILURE_OCIR_UNREACHABLE" ;;
    *"Could not connect"*|*"timed out"*|*RequestException*|*'"status": 429'*|*'"status": 5'[0-9][0-9]*)
      printf '%s' "$ACX_OCIR_FAILURE_VAULT_UNREACHABLE" ;;
    *ServiceError*)
      printf '%s' "$ACX_OCIR_FAILURE_VAULT_REQUEST" ;;
    *[Uu]nauthorized*|*"401"*|*"authentication required"*)
      printf '%s' "$ACX_OCIR_FAILURE_OCIR_REJECTED" ;;
    *) printf '%s' "$ACX_OCIR_FAILURE_UNKNOWN" ;;
  esac
}

# Return only a normalized classification. Raw stderr from a program that
# consumed a credential is never safe to replay: some clients echo stdin in
# debug or error output.
ocir_safe_login_diagnostic() {
  printf 'acx-safe-login-error:%s (credential-bearing stderr suppressed)' \
    "$(ocir_classify_login_failure "$1")"
}

ocir_login_failure_hint() {
  case "$1" in
    "$ACX_OCIR_FAILURE_OCI_CLI_MISSING")
      printf 'oci-cli not found. Install it on the host: python3 -m venv ~/.oci-venv && ~/.oci-venv/bin/pip install oci-cli' ;;
    "$ACX_OCIR_FAILURE_DOCKER_CLI_MISSING")
      printf 'Docker CLI not found on the host. Install Docker before retrying OCIR authentication.' ;;
    "$ACX_OCIR_FAILURE_SECRET_MISSING")
      printf 'A required OCIR secret is missing from acx-vault (or has no ACTIVE version). Store OCIR_USERNAME and OCIR_AUTH_TOKEN with: make ocir-token-rotate' ;;
    "$ACX_OCIR_FAILURE_VAULT_DENIED")
      printf 'The first required OCIR secret could not be read: it may be missing (or have no ACTIVE version), or the host may lack IAM access. Check OCIR_USERNAME/OCIR_AUTH_TOKEN in acx-vault and confirm dynamic-group acx-backend-dg plus policy acx-backend-secret-read still grant SECRET_BUNDLE_READ.' ;;
    "$ACX_OCIR_FAILURE_VAULT_UNREACHABLE")
      printf 'OCI Vault unreachable or slower than %ss. Transient -- retry; if it persists, check egress from the host.' "${ACX_VAULT_FETCH_TIMEOUT}" ;;
    "$ACX_OCIR_FAILURE_VAULT_REQUEST")
      printf 'OCI Vault rejected the request as non-transient. Check the reported status/code and correct the request or Vault configuration before retrying.' ;;
    "$ACX_OCIR_FAILURE_OCIR_UNREACHABLE")
      printf 'OCIR login was unreachable or slower than %ss. Transient -- retry; if it persists, check registry egress.' "${ACX_VAULT_FETCH_TIMEOUT}" ;;
    "$ACX_OCIR_FAILURE_OCIR_REJECTED")
      printf 'Vault returned a token but OCIR rejected it -- the stored token is revoked or expired. Mint a replacement (Console > My Profile > Auth tokens) and store it with: make ocir-token-rotate' ;;
    "$ACX_OCIR_FAILURE_CREDENTIAL_INCONSISTENT")
      printf 'The OCIR credential generation is changing or incomplete. Retry shortly; if it persists, rerun the token rotation recovery.' ;;
    "$ACX_OCIR_FAILURE_SSH")
      printf 'SSH failed before remote OCIR authentication completed. Check the ssh executable, remote shell, and target host.' ;;
    *)
      printf 'Unclassified OCIR login failure; see the raw stderr above.' ;;
  esac
}
