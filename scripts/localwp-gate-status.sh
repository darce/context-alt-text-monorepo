#!/usr/bin/env bash
#
# localwp-gate-status.sh — Summarize the LocalWP E15-3a gate state as JSON.
#
# Usage:
#   ./scripts/localwp-gate-status.sh --wp-path "$HOME/Development/wp-context-alt-text/app/public"
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_WP_WRAPPER="${SCRIPT_DIR}/localwp-wp.sh"
WP_WRAPPER="${LOCALWP_GATE_WP_WRAPPER:-${DEFAULT_WP_WRAPPER}}"
WP_PATH=""

show_usage() {
	cat <<'USAGE'
Usage:
  ./scripts/localwp-gate-status.sh --wp-path /path/to/wordpress/root

Environment overrides:
  LOCALWP_GATE_WP_WRAPPER  Alternate wp wrapper command (defaults to scripts/localwp-wp.sh)
USAGE
}

while (($# > 0)); do
	case "$1" in
		--wp-path)
			WP_PATH="${2:-}"
			shift 2
			;;
		--help|-h)
			show_usage
			exit 0
			;;
		*)
			echo "Unknown argument: $1" >&2
			show_usage >&2
			exit 1
			;;
	esac
done

if [[ -z "${WP_PATH}" ]]; then
	echo "Error: --wp-path is required." >&2
	show_usage >&2
	exit 1
fi

if [[ ! -x "${WP_WRAPPER}" ]]; then
	echo "Error: LocalWP wp wrapper missing or not executable: ${WP_WRAPPER}" >&2
	exit 1
fi

run_wp() {
	"${WP_WRAPPER}" --path="${WP_PATH}" "$@"
}

SITE_URL="$(run_wp option get siteurl | sed -n '/./{s/^[[:space:]]*//;s/[[:space:]]*$//;p;q;}')"
PLUGIN_TEXT="$(run_wp plugin status alt-context)"
PLUGIN_STATUS="$(printf '%s\n' "${PLUGIN_TEXT}" | sed -n 's/^[[:space:]]*Status:[[:space:]]*//p' | head -n 1)"
PLUGIN_VERSION="$(printf '%s\n' "${PLUGIN_TEXT}" | sed -n 's/^[[:space:]]*Version:[[:space:]]*//p' | head -n 1)"
TENANT_UUID="$(run_wp eval 'echo \AltContext\Api\TenantIdentity::resolve()["value"];')"

SETTINGS_JSON="$(run_wp eval 'wp_set_current_user(1); $request = new WP_REST_Request("GET", "/acx/v1/settings"); $response = rest_do_request($request); echo wp_json_encode($response->get_data(), JSON_UNESCAPED_SLASHES);')"
PROBE_JSON="$(run_wp eval 'wp_set_current_user(1); $request = new WP_REST_Request("POST", "/acx/v1/settings/test"); $response = rest_do_request($request); echo wp_json_encode($response->get_data(), JSON_UNESCAPED_SLASHES);')"
FINGERPRINT_JSON="$(run_wp eval 'wp_set_current_user(1); $request = new WP_REST_Request("GET", "/acx/v1/settings"); $response = rest_do_request($request); $data = $response->get_data(); $source = (string) ($data["key_source"] ?? "default"); $raw = ""; if ("constant" === $source && defined("ACX_RECOGNITION_API_KEY") && is_string(ACX_RECOGNITION_API_KEY)) { $raw = trim(ACX_RECOGNITION_API_KEY); } elseif ("option" === $source) { $raw = trim((string) get_option("acx_recognition_api_key", "")); } elseif ("filter" === $source) { $raw = trim((string) apply_filters("acx_recognition_api_key", "")); } $fingerprint = "" !== $raw ? substr(hash("sha256", $raw), 0, 12) : null; echo wp_json_encode(array("fingerprint" => $fingerprint, "source" => $source), JSON_UNESCAPED_SLASHES);')"

SITE_URL="${SITE_URL}" \
TENANT_UUID="${TENANT_UUID}" \
PLUGIN_STATUS="${PLUGIN_STATUS}" \
PLUGIN_VERSION="${PLUGIN_VERSION}" \
SETTINGS_JSON="${SETTINGS_JSON}" \
PROBE_JSON="${PROBE_JSON}" \
FINGERPRINT_JSON="${FINGERPRINT_JSON}" \
python3 - <<'PY'
import json
import os

payload = {
    "site_url": os.environ["SITE_URL"].strip(),
    "tenant_uuid": os.environ["TENANT_UUID"].strip(),
    "plugin": {
        "status": os.environ["PLUGIN_STATUS"].strip(),
        "version": os.environ["PLUGIN_VERSION"].strip(),
    },
    "settings": json.loads(os.environ["SETTINGS_JSON"]),
    "effective_key": json.loads(os.environ["FINGERPRINT_JSON"]),
    "probe": json.loads(os.environ["PROBE_JSON"]),
}
print(json.dumps(payload, indent=2, sort_keys=True))
PY
