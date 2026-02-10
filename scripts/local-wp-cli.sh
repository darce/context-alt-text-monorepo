#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${LOCALWP_SITE_PATH:-}" ]]; then
  echo "LOCALWP_SITE_PATH must point to your LocalWP site's app/public directory." >&2
  exit 1
fi

if [[ -z "${LOCALWP_MYSQL_SOCKET:-}" ]]; then
  echo "LOCALWP_MYSQL_SOCKET must point to the LocalWP MySQL socket file." >&2
  exit 1
fi

WP_BIN="${WP_BIN:-wp}"
SITE_URL="${LOCALWP_SITE_URL:-http://alt-context.local}"
SOCKET_ARG="-d mysqli.default_socket=${LOCALWP_MYSQL_SOCKET}"
CMD=("$WP_BIN" "--path=${LOCALWP_SITE_PATH}")

if [[ -n "${SITE_URL}" ]]; then
  CMD+=("--url=${SITE_URL}")
fi

CMD+=("$@")

if [[ -n "${ACX_WP_CLI_DRY_RUN:-}" ]]; then
  printf 'WP_CLI_PHP_ARGS=%s%s\n' "${WP_CLI_PHP_ARGS:-}" "${WP_CLI_PHP_ARGS:+ }${SOCKET_ARG}"
  printf 'CMD=%s\n' "${CMD[*]}"
  exit 0
fi

if [[ -n "${WP_CLI_PHP_ARGS:-}" ]]; then
  export WP_CLI_PHP_ARGS="${WP_CLI_PHP_ARGS} ${SOCKET_ARG}"
else
  export WP_CLI_PHP_ARGS="${SOCKET_ARG}"
fi

exec "${CMD[@]}"
