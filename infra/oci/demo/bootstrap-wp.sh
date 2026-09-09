#!/usr/bin/env bash
# Non-interactive WordPress install + ACX plugin activation for the OCI demo stack.
#
# Implements the Slice 2 bootstrap sequence from E15-28:
#   1. Ensure compose stack is up (MariaDB healthy, WordPress volume seeded)
#   2. Wait until wp-cli can reach the DB cleanly
#   3. wp core install (idempotent via wp core is-installed gate)
#   4. Install + activate the packaged alt-context plugin zip
#
# Usage (on the VM):
#   cd /opt/acx-backend/demo
#   PLUGIN_ZIP=/tmp/alt-context.zip ./bootstrap-wp.sh
#
# Environment:
#   DEMO_DIR          default /opt/acx-backend/demo
#   COMPOSE_FILE      default docker-compose.demo.yml
#   PLUGIN_ZIP        path to dist/alt-context-<version>.zip (required for plugin step)
#   WP_URL            default https://demo.altcontext.com
#   WP_TITLE          default ACX Demo
#   ACX_DEMO_DESCRIBE_CHUNK  first describe publish chunk size (default 10)
#   ACX_DEMO_DESCRIBE_MAX    maximum first describe publish size (default 100)

set -euo pipefail

DEMO_DIR="${DEMO_DIR:-/opt/acx-backend/demo}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.demo.yml}"
PLUGIN_ZIP="${PLUGIN_ZIP:-}"
WP_URL="${WP_URL:-https://demo.altcontext.com}"
WP_TITLE="${WP_TITLE:-ACX Demo}"
ACX_DEMO_DESCRIBE_CHUNK="${ACX_DEMO_DESCRIBE_CHUNK:-10}"
ACX_DEMO_DESCRIBE_MAX="${ACX_DEMO_DESCRIBE_MAX:-100}"

# Fail-closed describe-apply: canned `seeded` captions are worse than empty alt.
# BOOTSTRAP_GPU_CONTRACT_BEGIN
# Repository invocations use the identical source without a generated copy.
bootstrap_contract="$(dirname "${BASH_SOURCE[0]}")/lib/gpu-env-contract.sh"
if [[ ! -r "$bootstrap_contract" ]]; then
  bootstrap_contract="$(dirname "${BASH_SOURCE[0]}")/../../../scripts/deploy/lib/gpu-env-contract.sh"
fi
# shellcheck source=../../../scripts/deploy/lib/gpu-env-contract.sh
if [[ ! -r "$bootstrap_contract" ]]; then
  echo "ERROR: missing staged lib/gpu-env-contract.sh; deploy must transfer it before bootstrap." >&2
  exit 2
fi
source "$bootstrap_contract"
# BOOTSTRAP_GPU_CONTRACT_END

cd "$DEMO_DIR"

DESCRIBE_BURST_MARKER="${DEMO_DIR}/.acx-describe-first-burst.count"
rm -f "$DESCRIBE_BURST_MARKER"

if [[ ! -f secrets/.env ]]; then
  echo "ERROR: ${DEMO_DIR}/secrets/.env missing — copy from secrets/.env.example" >&2
  exit 2
fi
ln -sf secrets/.env .env

# secrets/.env is a docker-compose dotenv, not a shell file — the documented
# WORDPRESS_CONFIG_EXTRA value (unquoted define(...) line) is a bash syntax
# error under `source`. Parse the keys we need instead of sourcing.
env_get() {
  grep -m1 "^${1}=" secrets/.env | cut -d= -f2- || true
}

WP_ADMIN_USER="$(env_get WP_ADMIN_USER)"
WP_ADMIN_PASSWORD="$(env_get WP_ADMIN_PASSWORD)"
WP_ADMIN_EMAIL="$(env_get WP_ADMIN_EMAIL)"
WP_CI_USER="$(env_get WP_CI_USER)"
WP_CI_PASSWORD="$(env_get WP_CI_PASSWORD)"
WP_CI_EMAIL="$(env_get WP_CI_EMAIL)"
WORDPRESS_CONFIG_EXTRA="$(acx_env_literal_value "$(env_get WORDPRESS_CONFIG_EXTRA)")"

for var in WP_ADMIN_USER WP_ADMIN_PASSWORD WP_ADMIN_EMAIL WP_CI_USER WP_CI_PASSWORD WP_CI_EMAIL WORDPRESS_CONFIG_EXTRA; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: ${var} must be set in secrets/.env before bootstrap" >&2
    exit 2
  fi
done

# AUTH_CREDENTIAL_FUNCS_BEGIN
# Idempotent WP user password converge. First install still uses `wp core
# install`; every later run must rotate when secrets/.env changed (AUTH-01).
# A credential that cannot be rotated cannot be revoked. Fail loud on update
# or post-update verify failure — never skip. wpcli is the seam (defined
# below; looked up at call time).
wp_user_password_matches() {
  local user="$1"
  local password="$2"
  wpcli wp user check-password "$user" "$password" >/dev/null 2>&1
}

converge_wp_user_password() {
  local user="$1"
  local password="$2"
  if wp_user_password_matches "$user" "$password"; then
    echo "==> WP credential unchanged for user=${user} — no-op"
    return 0
  fi
  echo "==> WP secret changed for user=${user} — rotating via wp user update"
  if ! wpcli wp user update "$user" --user_pass="$password"; then
    echo "ERROR: failed to rotate WordPress credential for user '${user}'" >&2
    return 2
  fi
  if ! wp_user_password_matches "$user" "$password"; then
    echo "ERROR: WordPress credential for user '${user}' did not converge after update" >&2
    return 2
  fi
  echo "==> WP credential rotated for user=${user}"
  return 0
}

# AUTH-03: dedicated CI identity, not administrator and not the demo admin login.
# manage_options is the plugin admin cap the deploy-smoke needs; subscriber
# clone keeps delete_users / install_plugins / update_core off this principal.
WP_CI_ROLE_NAME="acx_ci"

ensure_wp_ci_role() {
  if ! wpcli wp role exists "$WP_CI_ROLE_NAME" >/dev/null 2>&1; then
    if ! wpcli wp role create "$WP_CI_ROLE_NAME" "ACX CI" --clone=subscriber; then
      echo "ERROR: failed to create least-privilege CI role ${WP_CI_ROLE_NAME}" >&2
      return 2
    fi
  fi
  # Idempotent re-grant: a failed first cap-add must not leave a sticky
  # under-privileged role on later bootstraps (wp cap add is additive).
  if ! wpcli wp cap add "$WP_CI_ROLE_NAME" manage_options; then
    echo "ERROR: failed to grant manage_options to ${WP_CI_ROLE_NAME}" >&2
    return 2
  fi
  # workbench GET /workbench/media permission_callback is upload_files
  # (class-api.php can_view_media_queue); without it CI smoke 403s and the
  # walkthrough silently degrades to screenshots-only.
  if ! wpcli wp cap add "$WP_CI_ROLE_NAME" upload_files; then
    echo "ERROR: failed to grant upload_files to ${WP_CI_ROLE_NAME}" >&2
    return 2
  fi
}

converge_wp_ci_account() {
  local ci_user="$1"
  local ci_password="$2"
  local ci_email="$3"
  local admin_user="$4"
  local admin_email="$5"
  if [[ -z "$ci_user" || -z "$ci_password" || -z "$ci_email" ]]; then
    echo "ERROR: WP_CI_USER, WP_CI_PASSWORD, and WP_CI_EMAIL must be set (CI account is distinct from WP admin)" >&2
    return 2
  fi
  if [[ -z "$admin_email" ]]; then
    echo "ERROR: WP_ADMIN_EMAIL must be set so CI email cannot collide with demo admin email" >&2
    return 2
  fi
  if [[ "${ci_user,,}" == "${admin_user,,}" ]]; then
    echo "ERROR: WP_CI_USER must differ from WP_ADMIN_USER (CI must not share the demo admin login)" >&2
    return 2
  fi
  if [[ "${ci_email,,}" == "${admin_email,,}" ]]; then
    echo "ERROR: WP_CI_EMAIL must differ from WP_ADMIN_EMAIL (CI must not share the demo admin mailbox)" >&2
    return 2
  fi
  ensure_wp_ci_role || return 2
  if wpcli wp user get "$ci_user" --field=ID >/dev/null 2>&1; then
    converge_wp_user_password "$ci_user" "$ci_password" || return 2
    if ! wpcli wp user set-role "$ci_user" "$WP_CI_ROLE_NAME"; then
      echo "ERROR: failed to pin CI user '${ci_user}' to role ${WP_CI_ROLE_NAME}" >&2
      return 2
    fi
    local current_email
    current_email=$(wpcli wp user get "$ci_user" --field=user_email 2>/dev/null | tr -d '\r')
    if [[ "${current_email,,}" != "${ci_email,,}" ]]; then
      if ! wpcli wp user update "$ci_user" --user_email="$ci_email"; then
        echo "ERROR: failed to converge CI email for user '${ci_user}'" >&2
        return 2
      fi
    fi
    return 0
  fi
  if ! wpcli wp user create "$ci_user" "$ci_email" --user_pass="$ci_password" --role="$WP_CI_ROLE_NAME"; then
    echo "ERROR: failed to create CI WordPress user '${ci_user}'" >&2
    return 2
  fi
  if ! converge_wp_user_password "$ci_user" "$ci_password"; then
    echo "ERROR: CI WordPress credential for user '${ci_user}' did not converge after create" >&2
    return 2
  fi
  echo "==> CI WordPress user created user=${ci_user} role=${WP_CI_ROLE_NAME}"
  return 0
}
# AUTH_CREDENTIAL_FUNCS_END

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

wpcli() {
  compose run --rm --no-deps wpcli "$@"
}

echo "==> Starting demo stack services"
compose up -d mariadb wordpress

echo "==> Waiting for WordPress volume + database readiness"
# Ready means: core files AND wp-config.php exist (the entrypoint writes
# wp-config.php after the volume seed), and wp-cli reaches the DB. wp-cli
# exits 1 both for "not installed" and for runtime errors, so a DB-unreachable
# error must keep us polling instead of counting as "ready, not installed".
ready=0
for _ in $(seq 1 60); do
  if compose exec -T wordpress test -f /var/www/html/wp-includes/version.php 2>/dev/null \
    && compose exec -T wordpress test -f /var/www/html/wp-config.php 2>/dev/null; then
    if install_out=$(wpcli wp core is-installed 2>&1); then
      ready=1
      break
    elif ! grep -qiE 'error establishing|connection refused|could not find|wp-config' <<<"$install_out"; then
      ready=1
      break
    fi
  fi
  sleep 5
done

if [[ "$ready" -ne 1 ]]; then
  echo "ERROR: WordPress did not become ready for wp-cli within timeout" >&2
  exit 2
fi

echo "==> Ensuring WordPress core is installed"
if ! wpcli wp core is-installed >/dev/null 2>&1; then
  wpcli wp core install \
    --url="$WP_URL" \
    --title="$WP_TITLE" \
    --admin_user="$WP_ADMIN_USER" \
    --admin_password="$WP_ADMIN_PASSWORD" \
    --admin_email="$WP_ADMIN_EMAIL" \
    --skip-email
fi
# AUTH-01: secrets/.env is the source of truth on every run, not only first
# install. Unchanged password is a no-op; a changed password must land or
# this script exits non-zero (a credential you cannot rotate you cannot revoke).
if ! converge_wp_user_password "$WP_ADMIN_USER" "$WP_ADMIN_PASSWORD"; then
  exit 2
fi
if ! converge_wp_ci_account "$WP_CI_USER" "$WP_CI_PASSWORD" "$WP_CI_EMAIL" "$WP_ADMIN_USER" "$WP_ADMIN_EMAIL"; then
  exit 2
fi

# Pretty permalinks are required for path-form REST (/wp-json/...): on the
# default Plain structure WordPress canonical-redirects /wp-json/* to the
# homepage (301 -> HTML), which breaks any client that hardcodes /wp-json/
# (e.g. the deploy-smoke walkthrough spec). rewrite_structure() is idempotent;
# --hard also rewrites .htaccess inside the Apache-based wordpress image.
echo "==> Ensuring pretty permalink structure (path-form /wp-json REST)"
wpcli wp rewrite structure '/%postname%/' --hard
wpcli wp rewrite flush --hard

if [[ -z "$PLUGIN_ZIP" ]]; then
  echo "ERROR: PLUGIN_ZIP must point at dist/alt-context-<version>.zip" >&2
  exit 2
fi
if [[ ! -f "$PLUGIN_ZIP" ]]; then
  echo "ERROR: PLUGIN_ZIP not found: $PLUGIN_ZIP" >&2
  exit 2
fi

echo "==> Installing and activating alt-context plugin"
# --force: overwrite an existing plugin dir so redeploys are idempotent
# (without it, wp exits non-zero on "Destination folder already exists").
compose run --rm --no-deps \
  -v "${PLUGIN_ZIP}:/tmp/alt-context.zip:ro" \
  wpcli wp plugin install /tmp/alt-context.zip --activate --force

# Cycle activation: a --force update over an already-active plugin does NOT
# re-fire the activation hook, so LifeCycleManager's dbDelta schema upgrade
# never runs and new plugin columns (e.g. claimed_at, 2026-07-12) are missing
# at runtime. Deactivate/activate forces the upgrade; both are idempotent.
echo "==> Cycle plugin activation so activation-hook dbDelta applies schema changes"
compose run --rm --no-deps wpcli wp plugin deactivate alt-context || true
compose run --rm --no-deps wpcli wp plugin activate alt-context

# Activation runs after init; flush in a fresh request where the enabled guide
# has registered its rewrite, so an update cannot leave /guide/ returning 404.
wpcli wp rewrite flush

# wp-cli --format=count -> digits, or "" on failure/non-numeric so the
# classifier BLOCKs instead of guessing.
wpcli_count_or_empty() {
  local out
  if ! out=$(wpcli "$@" 2>/dev/null); then
    echo ""
    return 0
  fi
  out=$(printf '%s' "$out" | tr -d '[:space:]')
  case "$out" in
    *[!0-9]*|'') echo "" ;;
    *) echo "$out" ;;
  esac
}

count_total_media() {
  wpcli_count_or_empty wp post list --post_type=attachment --post_status=inherit --format=count
}

count_media_with_alt() {
  wpcli_count_or_empty wp post list --post_type=attachment --post_status=inherit \
    --meta_key=_wp_attachment_image_alt --meta_compare='!=' --meta_value='' --format=count
}

validate_describe_bounds() {
  case "$ACX_DEMO_DESCRIBE_CHUNK" in
    ''|*[!0-9]*)
      echo "ERROR: ACX_DEMO_DESCRIBE_CHUNK must be a positive integer" >&2
      return 1
      ;;
  esac
  case "$ACX_DEMO_DESCRIBE_MAX" in
    ''|*[!0-9]*)
      echo "ERROR: ACX_DEMO_DESCRIBE_MAX must be a positive integer" >&2
      return 1
      ;;
  esac
  if (( ACX_DEMO_DESCRIBE_CHUNK < 1 || ACX_DEMO_DESCRIBE_MAX < 1 )); then
    echo "ERROR: ACX_DEMO_DESCRIBE_CHUNK and ACX_DEMO_DESCRIBE_MAX must be positive" >&2
    return 1
  fi
}

write_describe_burst_marker() {
  local count="$1"
  if ! printf '%s\n' "$count" >"$DESCRIBE_BURST_MARKER"; then
    echo "ERROR: cannot record bounded describe publish marker at ${DESCRIBE_BURST_MARKER}" >&2
    return 1
  fi
}

refresh_describe_provenance() {
  local sample
  if sample=$(sample_published_alt_text); then
    PROVENANCE="$(classify_describe_provenance "$sample")"
  else
    PROVENANCE="UNKNOWN"
  fi
}

echo "==> Describe-apply gate (fail-closed; seeded captions are worse than empty alt)"

# Probe the RUNNING description service for description_adapter (DEMOLIVE-8
# contract on GET /health/detailed). Auth and base URL come from the same
# WORDPRESS_CONFIG_EXTRA defines this script already loads — never from
# ACX_DESCRIPTION_ADAPTER in secrets/.env (that name is not wired into the
# producer). Probe failure / non-2xx / missing field -> empty -> BLOCK.
PROBED_BASE_URL_FILE="$(mktemp)"
trap 'rm -f "$PROBED_BASE_URL_FILE"' EXIT

probe_live_description_adapter() {
  local base_url api_key tenant_id body_file code body
  base_url="$(php_define_value ACX_RECOGNITION_URL "$WORDPRESS_CONFIG_EXTRA")"
  api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$WORDPRESS_CONFIG_EXTRA")"
  tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$WORDPRESS_CONFIG_EXTRA")"
  # Named for the BLOCK message so a probe failure can quote the endpoint it
  # actually tried. Runs in a subshell, so write it to a file, not a variable.
  # Store the normalized form: curl requests "${base_url%/}/health/detailed",
  # so printing the raw value would hand the operator a doubled-slash URL that
  # was never requested.
  printf '%s' "${base_url:+${base_url%/}}" > "$PROBED_BASE_URL_FILE"
  [ -n "$base_url" ] || printf '%s' "<ACX_RECOGNITION_URL unset>" > "$PROBED_BASE_URL_FILE"
  if [[ -z "$base_url" || -z "$api_key" ]]; then
    echo ""
    return 0
  fi
  body_file=$(mktemp)
  code=$(curl -sS -o "$body_file" -w '%{http_code}' --max-time 10 \
    -H "X-Api-Key: ${api_key}" \
    -H "X-Tenant-ID: ${tenant_id}" \
    "${base_url%/}/health/detailed" 2>/dev/null) || code="000"
  body=$(cat "$body_file" 2>/dev/null || true)
  rm -f "$body_file"
  extract_probed_description_adapter "$code" "$body"
}

sample_published_alt_text() {
  local out
  if ! out=$(wpcli wp eval 'foreach (get_posts(array("post_type"=>"attachment","post_status"=>"inherit","numberposts"=>100,"fields"=>"ids")) as $id) { $alt = get_post_meta($id, "_wp_attachment_image_alt", true); if (is_string($alt) && $alt !== "") { echo $alt, "\n"; } }' 2>/dev/null); then
    return 1
  fi
  printf '%s' "$out"
}

ADAPTER_PROFILE="$(probe_live_description_adapter)"
TOTAL_MEDIA="$(count_total_media)"
MEDIA_WITH_ALT="$(count_media_with_alt)"
if ! validate_describe_bounds; then
  exit 1
fi

PROVENANCE="UNKNOWN"
case "$MEDIA_WITH_ALT" in
  ''|*[!0-9]*) PROVENANCE="UNKNOWN" ;;
  0) PROVENANCE="PASS" ;;
  *)
    refresh_describe_provenance
    ;;
esac

DESCRIBE_VERDICT="$(classify_describe_gate "$ADAPTER_PROFILE" "$TOTAL_MEDIA" "$MEDIA_WITH_ALT" "$PROVENANCE")"

case "$DESCRIBE_VERDICT" in
  RUN|RUN_FORCE)
    describe_force=0
    if [[ "$DESCRIBE_VERDICT" == "RUN_FORCE" ]]; then
      describe_force=1
    fi
    describe_chunk_number=0
    describe_admitted=0
    # A normal run only needs to admit the media that still lacks usable alt
    # text. RUN_FORCE deliberately rewrites an already-covered population, so
    # its bounded repair burst may use the full live population as its budget.
    describe_media_budget="$TOTAL_MEDIA"
    if (( ! describe_force )); then
      describe_media_budget=$((TOTAL_MEDIA - MEDIA_WITH_ALT))
    fi
    # The historical single-pass force form was `describe generate --write --force --limit=100`.
    # Keep each request bounded while allowing coverage to converge in chunks.
    while :; do
      # RUN_FORCE must issue one chunk even when the current coverage is full:
      # that is the repair path for already-published but untrusted captions.
      if (( describe_chunk_number > 0 && MEDIA_WITH_ALT >= TOTAL_MEDIA )); then
        break
      fi
      if (( describe_admitted >= ACX_DEMO_DESCRIBE_MAX || describe_admitted >= describe_media_budget )); then
        break
      fi
      remaining=$((ACX_DEMO_DESCRIBE_MAX - describe_admitted))
      remaining_media=$((describe_media_budget - describe_admitted))
      chunk_limit="$ACX_DEMO_DESCRIBE_CHUNK"
      if (( chunk_limit > remaining )); then
        chunk_limit="$remaining"
      fi
      if (( chunk_limit > remaining_media )); then
        chunk_limit="$remaining_media"
      fi
      if (( chunk_limit < 1 )); then
        break
      fi
      describe_chunk_number=$((describe_chunk_number + 1))
      describe_before="$MEDIA_WITH_ALT"
      echo "==> Describe chunk ${describe_chunk_number} before: coverage=${describe_before}/${TOTAL_MEDIA} admitted=${describe_admitted}/${ACX_DEMO_DESCRIBE_MAX} limit=${chunk_limit} provenance=${PROVENANCE}"
      if (( describe_force )); then
        wpcli wp alt-context describe generate --write --force --limit="$chunk_limit"
      else
        wpcli wp alt-context describe generate --write --limit="$chunk_limit"
      fi
      describe_admitted=$((describe_admitted + chunk_limit))
      MEDIA_WITH_ALT="$(count_media_with_alt)"
      echo "==> Describe chunk ${describe_chunk_number} after: coverage=${MEDIA_WITH_ALT:-empty}/${TOTAL_MEDIA} admitted=${describe_admitted}/${ACX_DEMO_DESCRIBE_MAX}"

      coverage_unmeasurable=0
      case "$TOTAL_MEDIA" in *[!0-9]*|'') coverage_unmeasurable=1 ;; esac
      case "$MEDIA_WITH_ALT" in *[!0-9]*|'') coverage_unmeasurable=1 ;; esac
      if [[ "$coverage_unmeasurable" -eq 0 && "$MEDIA_WITH_ALT" -gt "$TOTAL_MEDIA" ]]; then
        coverage_unmeasurable=1
      fi
      if [[ "$coverage_unmeasurable" -eq 1 ]]; then
        echo "==> BLOCKED: cannot measure demo media coverage after describe chunk ${describe_chunk_number} (total='${TOTAL_MEDIA}' with_alt='${MEDIA_WITH_ALT}'). Describe publish stopped fail closed." >&2
        exit 1
      fi

      # A service can drift while a multi-chunk publish is in flight. Re-sample
      # after the first chunk (and every later chunk) before admitting another
      # request; a newly untrusted producer stops the burst immediately.
      refresh_describe_provenance
      echo "==> Describe chunk ${describe_chunk_number} provenance: ${PROVENANCE}"
      if [[ "$PROVENANCE" != "PASS" ]]; then
        echo "==> BLOCKED: description provenance became untrusted after describe chunk ${describe_chunk_number} (got '${PROVENANCE}'). Describe publish stopped fail closed." >&2
        write_describe_burst_marker "$describe_admitted" || true
        exit 1
      fi
      write_describe_burst_marker "$describe_admitted"
    done
    echo "==> Describe burst bounded: admitted=${describe_admitted}/${ACX_DEMO_DESCRIBE_MAX} chunks=${describe_chunk_number} coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA}"
    ;;
  SKIP)
    write_describe_burst_marker 0
    echo "==> Describe pass skipped (adapter=${ADAPTER_PROFILE} coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA} provenance=${PROVENANCE})"
    ;;
  *)
    if is_trusted_describe_profile "$ADAPTER_PROFILE"; then
      coverage_unmeasurable=0
      case "$TOTAL_MEDIA" in *[!0-9]*|'') coverage_unmeasurable=1 ;; esac
      case "$MEDIA_WITH_ALT" in *[!0-9]*|'') coverage_unmeasurable=1 ;; esac
      if [[ "$coverage_unmeasurable" -eq 0 && "$MEDIA_WITH_ALT" -gt "$TOTAL_MEDIA" ]]; then
        coverage_unmeasurable=1
      fi
      if [[ "$coverage_unmeasurable" -eq 1 ]]; then
        echo "==> BLOCKED: cannot measure demo media coverage (total='${TOTAL_MEDIA}' with_alt='${MEDIA_WITH_ALT}') — 'wp post list --format=count' failed or returned non-numeric output. Adapter '${ADAPTER_PROFILE}' is trusted; this is an environment fault, not a config fault. Describe pass skipped." >&2
      else
        echo "==> BLOCKED: cannot verify description provenance (got '${PROVENANCE}') for adapter '${ADAPTER_PROFILE}' (coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA}). Fail closed; this is an environment fault, not a config fault. Describe pass skipped." >&2
      fi
    elif [[ "$(classify_describe_block_cause "$ADAPTER_PROFILE")" == "PROBE_FAILED" ]]; then
      echo "==> BLOCKED: could not read the live description service adapter — GET $(cat "$PROBED_BASE_URL_FILE" 2>/dev/null)/health/detailed returned no usable description_adapter (non-2xx, timeout, missing/blank ACX_RECOGNITION_URL or ACX_RECOGNITION_API_KEY, or an unparseable body). This is a probe fault on the demo host — check the URL and credentials in the demo secrets/.env and that the service is reachable from this host. Do NOT change the producer's profile; nothing was read from it. (coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA})" >&2
    else
      echo "==> BLOCKED: refusing to publish descriptions — live description service adapter='${ADAPTER_PROFILE}' produces canned fixture captions, which is worse for accessibility than empty alt text. Change the description SERVICE profile (the running producer's ACX_DESCRIPTION_ADAPTER), not the demo host secrets/.env. Trusted service profiles: ${ACX_TRUSTED_DESCRIBE_PROFILES}. (coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA})" >&2
    fi
    exit 1
    ;;
esac

echo "==> Bootstrap complete — verify ACX constants inside the container:"
echo "    docker compose -f ${COMPOSE_FILE} exec wordpress php -r \"require '/var/www/html/wp-config.php'; var_export(defined('ACX_RECOGNITION_URL') ? ACX_RECOGNITION_URL : null);\""
