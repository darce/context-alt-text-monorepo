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
ADAPTER_PROFILE="$(env_get ACX_DESCRIPTION_ADAPTER)"
TOTAL_MEDIA="$(count_total_media)"
MEDIA_WITH_ALT="$(count_media_with_alt)"
DESCRIBE_VERDICT="$(classify_describe_gate "$ADAPTER_PROFILE" "$TOTAL_MEDIA" "$MEDIA_WITH_ALT")"

case "$DESCRIBE_VERDICT" in
  RUN)
    echo "==> Describe pass: wp alt-context describe generate --write --limit=100 (adapter=${ADAPTER_PROFILE} coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA})"
    wpcli wp alt-context describe generate --write --limit=100
    ;;
  SKIP)
    echo "==> Describe pass skipped (adapter=${ADAPTER_PROFILE} coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA})"
    ;;
  *)
    echo "==> BLOCKED: refusing to publish descriptions — ACX_DESCRIPTION_ADAPTER='${ADAPTER_PROFILE}' produces canned fixture captions, which is worse for accessibility than empty alt text. Set ACX_DESCRIPTION_ADAPTER to one of: florence_small, gpu_qwen30b, gpu_qwen30b_ensemble. (coverage=${MEDIA_WITH_ALT}/${TOTAL_MEDIA})" >&2
    ;;
esac

echo "==> Bootstrap complete — verify ACX constants inside the container:"
echo "    docker compose -f ${COMPOSE_FILE} exec wordpress php -r \"require '/var/www/html/wp-config.php'; var_export(defined('ACX_RECOGNITION_URL') ? ACX_RECOGNITION_URL : null);\""
