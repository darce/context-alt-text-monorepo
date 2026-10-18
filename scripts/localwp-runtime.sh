#!/usr/bin/env bash
#
# localwp-runtime.sh — Resolve LocalWP runtime paths without hard-coding hashes
#
# Usage:
#   ./scripts/localwp-runtime.sh socket
#   ./scripts/localwp-runtime.sh php-bin
#
# Environment overrides (optional):
#   LOCALWP_SOCKET   — full path to mysqld.sock
#   LOCALWP_PHP_BIN  — php executable path
#
set -euo pipefail

LOCAL_RUN_DIR="${HOME}/Library/Application Support/Local/run"

show_usage() {
	cat <<'USAGE'
Usage:
  ./scripts/localwp-runtime.sh socket
  ./scripts/localwp-runtime.sh php-bin

Subcommands:
  socket   Print the LocalWP MySQL socket path.
  php-bin  Print the PHP executable path.

Environment overrides:
  LOCALWP_SOCKET   Full path to mysqld.sock.
  LOCALWP_PHP_BIN  Full path to php executable.
USAGE
}

discover_socket() {
	if [[ -n "${LOCALWP_SOCKET:-}" ]]; then
		if [[ -S "${LOCALWP_SOCKET}" ]]; then
			echo "${LOCALWP_SOCKET}"
			return 0
		fi
		echo "Error: LOCALWP_SOCKET is set but '${LOCALWP_SOCKET}' is not a valid socket." >&2
		return 1
	fi

	if [[ ! -d "${LOCAL_RUN_DIR}" ]]; then
		echo "Error: LocalWP run directory not found at '${LOCAL_RUN_DIR}'." >&2
		echo "       Is LocalWP installed?" >&2
		return 1
	fi

	local sockets=()
	while IFS= read -r -d '' sock; do
		sockets+=("${sock}")
	done < <(find "${LOCAL_RUN_DIR}" -name "mysqld.sock" -print0 2>/dev/null)

	if [[ ${#sockets[@]} -eq 0 ]]; then
		echo "Error: No mysqld.sock found under '${LOCAL_RUN_DIR}'." >&2
		echo "       Is a LocalWP site running?" >&2
		return 1
	fi

	if [[ ${#sockets[@]} -gt 1 ]]; then
		echo "Warning: Multiple LocalWP MySQL sockets found. Using the first one." >&2
		echo "         Set LOCALWP_SOCKET to choose a specific one:" >&2
		for s in "${sockets[@]}"; do
			echo "           ${s}" >&2
		done
	fi

	echo "${sockets[0]}"
}

resolve_php_bin() {
	if [[ -n "${LOCALWP_PHP_BIN:-}" ]]; then
		if [[ -x "${LOCALWP_PHP_BIN}" ]]; then
			echo "${LOCALWP_PHP_BIN}"
			return 0
		fi
		echo "Error: LOCALWP_PHP_BIN is set but '${LOCALWP_PHP_BIN}' is not executable." >&2
		return 1
	fi

	if command -v php >/dev/null 2>&1; then
		command -v php
		return 0
	fi

	local candidates=(
		"/opt/homebrew/bin/php"
		"/usr/local/bin/php"
	)
	local candidate=""
	for candidate in "${candidates[@]}"; do
		if [[ -x "${candidate}" ]]; then
			echo "${candidate}"
			return 0
		fi
	done

	echo "Error: php not found on PATH or common Homebrew locations." >&2
	echo "       Install PHP or set LOCALWP_PHP_BIN explicitly." >&2
	return 1
}

COMMAND="${1:-}"

case "${COMMAND}" in
	socket)
		discover_socket
		;;
	php-bin)
		resolve_php_bin
		;;
	--help|-h|help)
		show_usage
		;;
	*)
		echo "Unknown or missing subcommand: '${COMMAND}'" >&2
		show_usage >&2
		exit 1
		;;
esac
