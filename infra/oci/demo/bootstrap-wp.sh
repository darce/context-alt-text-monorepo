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

set -euo pipefail

DEMO_DIR="${DEMO_DIR:-/opt/acx-backend/demo}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.demo.yml}"
PLUGIN_ZIP="${PLUGIN_ZIP:-}"
WP_URL="${WP_URL:-https://demo.altcontext.com}"
WP_TITLE="${WP_TITLE:-ACX Demo}"

cd "$DEMO_DIR"

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
WORDPRESS_CONFIG_EXTRA="$(env_get WORDPRESS_CONFIG_EXTRA)"

for var in WP_ADMIN_USER WP_ADMIN_PASSWORD WP_ADMIN_EMAIL WORDPRESS_CONFIG_EXTRA; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: ${var} must be set in secrets/.env before bootstrap" >&2
    exit 2
  fi
done

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

# Fail-closed describe-apply: canned `seeded` captions are worse than empty alt.
# shellcheck source=lib/describe-gate.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/describe-gate.sh"

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

echo "==> Describe-apply gate (fail-closed; seeded captions are worse than empty alt)"

# Probe the RUNNING description service for description_adapter (DEMOLIVE-8
# contract on GET /health/detailed). Auth and base URL come from the same
# WORDPRESS_CONFIG_EXTRA defines this script already loads — never from
# ACX_DESCRIPTION_ADAPTER in secrets/.env (that name is not wired into the
# producer). Probe failure / non-2xx / missing field -> empty -> BLOCK.
probe_live_description_adapter() {
  local base_url api_key tenant_id body_file code body
  base_url="$(php_define_value ACX_RECOGNITION_URL "$WORDPRESS_CONFIG_EXTRA")"
  api_key="$(php_define_value ACX_RECOGNITION_API_KEY "$WORDPRESS_CONFIG_EXTRA")"
  tenant_id="$(php_define_value ACX_RECOGNITION_TENANT_ID "$WORDPRESS_CONFIG_EXTRA")"
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

PROVENANCE="UNKNOWN"
case "$MEDIA_WITH_ALT" in
  ''|*[!0-9]*) PROVENANCE="UNKNOWN" ;;
  0) PROVENANCE="PASS" ;;
  *)
    if sample=$(sample_published_alt_text); then
      PROVENANCE="$(classify_describe_provenance "$sample")"
    else
      PROVENANCE="UNKNOWN"
    fi
    ;;
esac

DESCRIBE_VERDICT="$(classify_describe_gate "$ADAPTER_PROFILE" "$TOTAL_MEDIA" "$MEDIA_WITH_ALT" "$PROVENANCE")"

case "$DESCRIBE_VERDICT" in
  RUN)
    echo "==> Describe pass: wp alt-context describe generate --write --limit=100 (adapter=${ADAPTER_PROFILE} coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA} provenance=${PROVENANCE})"
    wpcli wp alt-context describe generate --write --limit=100
    ;;
  RUN_FORCE)
    echo "==> Describe pass (force overwrite): wp alt-context describe generate --write --force --limit=100 (adapter=${ADAPTER_PROFILE} coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA} provenance=${PROVENANCE})"
    wpcli wp alt-context describe generate --write --force --limit=100
    ;;
  SKIP)
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
    else
      echo "==> BLOCKED: refusing to publish descriptions — live description service adapter='${ADAPTER_PROFILE}' produces canned fixture captions, which is worse for accessibility than empty alt text. Change the description SERVICE profile (the running producer's ACX_DESCRIPTION_ADAPTER), not the demo host secrets/.env. Trusted service profiles: florence_small, gpu_qwen30b, gpu_qwen30b_ensemble. (coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA})" >&2
    fi
    exit 1
    ;;
esac

echo "==> Bootstrap complete — verify ACX constants inside the container:"
echo "    docker compose -f ${COMPOSE_FILE} exec wordpress php -r \"require '/var/www/html/wp-config.php'; var_export(defined('ACX_RECOGNITION_URL') ? ACX_RECOGNITION_URL : null);\""
