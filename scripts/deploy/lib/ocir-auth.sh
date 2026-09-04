#!/usr/bin/env bash
# OCIR docker-login credential resolution via OCI Vault (OCIRV-1).
#
# Replaces the cached-~/.docker/config.json credential that recognition-service.sh
# used to require. That credential had no owner, no expiry tracking, and no
# rotation path: recovery was a human Console click-path piped into `docker login`
# on every host. Release It! 5.4 (Steady State) names that shape directly --
# "if the system needs regular crank-turning, admins stay logged in, and fiddling
# follows; target: runs indefinitely without intervention" -- and [RLSE-11]
# rejects a deploy step that is a human click-path executed more than once.
#
# The token now lives in acx-vault as secret OCIR_AUTH_TOKEN alongside the
# secrets ADR-013 already moved there, and is fetched with the same mechanism
# infra/oci/vault-instance-principal-runbook.md section 4 prescribes for
# non-Python-app secrets (POSTGRES_PASSWORD):
#   oci secrets secret-bundle get-secret-bundle-by-name
#     - on the VM  : --auth instance_principal (dynamic-group acx-backend-dg,
#                    policy acx-backend-secret-read; no credential on the host)
#     - on a laptop: the operator's configured API key
#
# The token is never written to disk and never reaches argv (which is
# ps-visible): it is piped straight into `docker login --password-stdin`.
# Rotation is a new Vault secret version -- no host touch, no clipboard.
#
# Sourced by scripts/deploy/recognition-service.sh and by
# scripts/deploy/tests/test-ocir-auth.sh. Keep the pure functions
# dependency-free (no oci, no docker, no arrays) so they run under macOS
# bash 3.2 and the VM's bash.

# acx-vault (root compartment, us-ashburn-1). An OCID is not a secret -- ADR-013
# ships the secret map in plaintext for exactly this reason.
ACX_VAULT_OCID="${ACX_VAULT_OCID:-ocid1.vault.oc1.iad.ejvffpzlaafc4.abuwcljr3j4chidobdkiqx6igrzb4p3wffl43bjelxzfghkehdpuzle7cjla}"
ACX_OCIR_TOKEN_SECRET="${ACX_OCIR_TOKEN_SECRET:-OCIR_AUTH_TOKEN}"
ACX_OCIR_USERNAME_SECRET="${ACX_OCIR_USERNAME_SECRET:-OCIR_USERNAME}"
# oci-cli lives in a venv on the VM; it is not on PATH for non-login ssh shells.
ACX_REMOTE_OCI_BIN="${ACX_REMOTE_OCI_BIN:-\$HOME/.oci-venv/bin/oci}"
ACX_LOCAL_OCI_BIN="${ACX_LOCAL_OCI_BIN:-oci}"
# Bounded so a hung Vault call cannot stall the deploy.
ACX_VAULT_FETCH_TIMEOUT="${ACX_VAULT_FETCH_TIMEOUT:-30}"

# Emit the shell snippet that resolves one Vault secret to stdout, decoded.
# Pure string builder -- no I/O -- so tests can assert its shape without OCI.
# $1 = oci binary, $2 = --auth mode, $3 = secret name.
ocir_vault_fetch_snippet() {
  ocir__oci_bin="$1"
  ocir__auth_mode="$2"
  ocir__secret_name="$3"
  printf '%s --auth %s secrets secret-bundle get-secret-bundle-by-name --vault-id %s --secret-name %s --query %s --raw-output | base64 -d' \
    "${ocir__oci_bin}" "${ocir__auth_mode}" "${ACX_VAULT_OCID}" "${ocir__secret_name}" \
    "'data.\"secret-bundle-content\".content'"
}

# Emit the full fetch-and-login snippet for one host. The token is piped into
# --password-stdin: it never lands on disk and never appears in argv.
# $1 = oci binary, $2 = --auth mode, $3 = registry.
ocir_login_snippet() {
  ocir__bin="$1"
  ocir__auth="$2"
  ocir__registry="$3"
  printf 'set -eu\n'
  # `timeout` is coreutils: present on the VM, absent on stock macOS. Degrade to
  # an unwrapped call rather than failing the deploy on a missing helper.
  printf 'acx_t() { if command -v timeout >/dev/null 2>&1; then timeout %s "$@"; else "$@"; fi; }\n' \
    "${ACX_VAULT_FETCH_TIMEOUT}"
  printf 'acx_ocir_user="$(acx_t %s)"\n' \
    "$(ocir_vault_fetch_snippet "${ocir__bin}" "${ocir__auth}" "${ACX_OCIR_USERNAME_SECRET}")"
  # Progress sentinel. OCI deliberately collapses "not found" and "not
  # authorized" into one NotAuthorizedOrNotFound code so callers cannot probe
  # for a resource's existence. That leaves a missing secret indistinguishable
  # from a broken IAM policy -- and sends the operator to audit a policy that is
  # fine. Reaching this line proves this principal just read a secret from this
  # vault, so a later denial is about the token secret, not the grant.
  printf 'printf %s >&2\n' "'acx-vault-read-ok\\n'"
  printf 'acx_t %s | docker login %s -u "${acx_ocir_user}" --password-stdin >/dev/null\n' \
    "$(ocir_vault_fetch_snippet "${ocir__bin}" "${ocir__auth}" "${ACX_OCIR_TOKEN_SECRET}")" \
    "${ocir__registry}"
}

# Classify a fetch-and-login failure so the operator is told which of the three
# independent things broke. Release It! 5.5: report system failure (resources
# unavailable) differently from application failure. A Vault denial and an OCIR
# rejection need different fixes, and collapsing them into "auth failed" is what
# sent the previous session through a 20-pair username/endpoint matrix.
# $1 = combined stderr of the fetch+login.
ocir_classify_login_failure() {
  case "$1" in
    *"command not found"*|*"No such file or directory"*)
      printf 'oci_cli_missing' ;;
    *acx-vault-read-ok*NotAuthorizedOrNotFound*|*acx-vault-read-ok*"not authorized"*)
      # The vault was readable a line earlier, so the grant is intact.
      printf 'secret_missing' ;;
    *NotAuthenticated*|*NotAuthorizedOrNotFound*|*"not authorized"*)
      printf 'vault_denied' ;;
    *"Could not connect"*|*"timed out"*|*ServiceError*|*RequestException*)
      printf 'vault_unreachable' ;;
    *[Uu]nauthorized*|*"401"*|*"authentication required"*)
      printf 'ocir_rejected' ;;
    *) printf 'unknown' ;;
  esac
}

# Operator remediation per class. Only names the Console in the one case where
# Oracle genuinely requires it (the stored token was revoked, so a replacement
# must be minted by a human -- there is no API that returns the secret).
ocir_login_failure_hint() {
  case "$1" in
    oci_cli_missing)
      printf 'oci-cli not found. Install it on the host: python3 -m venv ~/.oci-venv && ~/.oci-venv/bin/pip install oci-cli' ;;
    secret_missing)
      printf 'The host can read acx-vault but %s is not in it (or has no ACTIVE version). Store one with: make ocir-token-rotate' "${ACX_OCIR_TOKEN_SECRET}" ;;
    vault_denied)
      printf 'Host cannot read acx-vault. Check dynamic-group acx-backend-dg still matches this instance and policy acx-backend-secret-read still grants SECRET_BUNDLE_READ.' ;;
    vault_unreachable)
      printf 'OCI Vault unreachable or slower than %ss. Transient -- retry; if it persists, check egress from the host.' "${ACX_VAULT_FETCH_TIMEOUT}" ;;
    ocir_rejected)
      printf 'Vault returned a token but OCIR rejected it -- the stored token is revoked or expired. Mint a replacement (Console > My Profile > Auth tokens) and store it with: make ocir-token-rotate' ;;
    *)
      printf 'Unclassified OCIR login failure; see the raw stderr above.' ;;
  esac
}
