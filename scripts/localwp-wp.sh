#!/usr/bin/env bash
#
# localwp-wp.sh — Run WP-CLI against LocalWP with durable PHP/socket resolution.
#
# Prefers a PHP 8.5-compatible wp-cli nightly when available. Otherwise it runs
# the stable Homebrew wp under php@8.4 when present to avoid known PHP 8.5
# deprecation noise from WP-CLI 2.12.0.
#
# Wrapper-specific commands:
#   ./scripts/localwp-wp.sh --print-plan
#   ./scripts/localwp-wp.sh --wrapper-help
#
# Environment overrides (optional):
#   LOCALWP_WP_BIN          Full path to a stable wp executable/phar.
#   LOCALWP_WP_NIGHTLY_BIN  Full path to a wp-nightly executable/phar.
#   LOCALWP_WP_PHP84_BIN    Full path to php@8.4 executable.
#   LOCALWP_WP_DISABLE_PHP84 Set to 1 to skip php@8.4 fallback resolution.
#   LOCALWP_WP_FILTER_KNOWN_NOISE Set to 1 to force filtering the known
#                                 WP-CLI 2.12.0 PHP 8.5 react/promise warning.
#   LOCALWP_SOCKET          Full path to mysqld.sock.
#   LOCALWP_PHP_BIN         Full path to the default php executable.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCALWP_RUNTIME_HELPER="${SCRIPT_DIR}/localwp-runtime.sh"

show_usage() {
	cat <<'USAGE'
Usage:
  ./scripts/localwp-wp.sh [wp-cli args...]

Wrapper-specific commands:
  --print-plan   Print the resolved mode/php/wp/socket values and exit.
  --wrapper-help Show this help text.

Examples:
  ./scripts/localwp-wp.sh --path="$HOME/Development/wp-context-alt-text/app/public" plugin status alt-context
  ./scripts/localwp-wp.sh --path="$HOME/Development/wp-context-alt-text/app/public" option get siteurl
USAGE
}

require_runtime_helper() {
	if [[ ! -x "${LOCALWP_RUNTIME_HELPER}" ]]; then
		echo "Error: LocalWP runtime helper missing or not executable: ${LOCALWP_RUNTIME_HELPER}" >&2
		exit 1
	fi
}

first_executable() {
	local candidate=""
	for candidate in "$@"; do
		if [[ -n "${candidate}" && -x "${candidate}" ]]; then
			echo "${candidate}"
			return 0
		fi
	done
	return 1
}

php_reports_major_minor() {
	local php_bin="$1"
	local expected="$2"
	local version=""
	version="$("${php_bin}" -r 'echo PHP_MAJOR_VERSION . "." . PHP_MINOR_VERSION;' 2>/dev/null || true)"
	[[ "${version}" == "${expected}" ]]
}

resolve_generic_php_bin() {
	require_runtime_helper
	"${LOCALWP_RUNTIME_HELPER}" php-bin
}

resolve_php84_bin() {
	if [[ "${LOCALWP_WP_DISABLE_PHP84:-0}" == "1" ]]; then
		return 1
	fi

	if [[ -n "${LOCALWP_WP_PHP84_BIN:-}" ]]; then
		if [[ -x "${LOCALWP_WP_PHP84_BIN}" ]]; then
			echo "${LOCALWP_WP_PHP84_BIN}"
			return 0
		fi
		echo "Error: LOCALWP_WP_PHP84_BIN is set but '${LOCALWP_WP_PHP84_BIN}' is not executable." >&2
		return 1
	fi

	local candidate=""
	for candidate in \
		"/opt/homebrew/opt/php@8.4/bin/php" \
		"/usr/local/opt/php@8.4/bin/php"
	do
		if [[ -x "${candidate}" ]] && php_reports_major_minor "${candidate}" "8.4"; then
			echo "${candidate}"
			return 0
		fi
	done

	return 1
}

resolve_nightly_wp_bin() {
	if [[ -n "${LOCALWP_WP_NIGHTLY_BIN:-}" ]]; then
		if [[ -x "${LOCALWP_WP_NIGHTLY_BIN}" ]]; then
			echo "${LOCALWP_WP_NIGHTLY_BIN}"
			return 0
		fi
		echo "Error: LOCALWP_WP_NIGHTLY_BIN is set but '${LOCALWP_WP_NIGHTLY_BIN}' is not executable." >&2
		return 1
	fi

	if command -v wp-nightly >/dev/null 2>&1; then
		command -v wp-nightly
		return 0
	fi

	first_executable \
		"${HOME}/.local/bin/wp-nightly" \
		"/opt/homebrew/bin/wp-nightly" \
		"/usr/local/bin/wp-nightly"
}

resolve_stable_wp_bin() {
	if [[ -n "${LOCALWP_WP_BIN:-}" ]]; then
		if [[ -x "${LOCALWP_WP_BIN}" ]]; then
			echo "${LOCALWP_WP_BIN}"
			return 0
		fi
		echo "Error: LOCALWP_WP_BIN is set but '${LOCALWP_WP_BIN}' is not executable." >&2
		return 1
	fi

	if command -v wp >/dev/null 2>&1; then
		command -v wp
		return 0
	fi

	first_executable \
		"/opt/homebrew/bin/wp" \
		"/usr/local/bin/wp"
}

discover_socket_or_empty() {
	require_runtime_helper
	LOCALWP_SOCKET="${LOCALWP_SOCKET:-}" "${LOCALWP_RUNTIME_HELPER}" socket 2>/dev/null || true
}

choose_runner() {
	local generic_php=""
	local nightly_wp=""
	local stable_wp=""
	local php84=""

	generic_php="$(resolve_generic_php_bin)"
	nightly_wp="$(resolve_nightly_wp_bin || true)"
	stable_wp="$(resolve_stable_wp_bin || true)"
	php84="$(resolve_php84_bin || true)"

	if [[ -n "${nightly_wp}" ]]; then
		CHOSEN_MODE="nightly"
		CHOSEN_PHP_BIN="${generic_php}"
		CHOSEN_WP_BIN="${nightly_wp}"
		return 0
	fi

	if [[ -n "${stable_wp}" && -n "${php84}" ]]; then
		CHOSEN_MODE="php84-stable"
		CHOSEN_PHP_BIN="${php84}"
		CHOSEN_WP_BIN="${stable_wp}"
		return 0
	fi

	if [[ -n "${stable_wp}" ]]; then
		CHOSEN_MODE="default"
		CHOSEN_PHP_BIN="${generic_php}"
		CHOSEN_WP_BIN="${stable_wp}"
		return 0
	fi

	echo "Error: wp not found. Install wp-nightly, wp, or set LOCALWP_WP_BIN." >&2
	return 1
}

print_plan() {
	local socket_path=""
	choose_runner
	socket_path="$(discover_socket_or_empty)"
	printf 'mode=%s\n' "${CHOSEN_MODE}"
	printf 'php_bin=%s\n' "${CHOSEN_PHP_BIN}"
	printf 'wp_bin=%s\n' "${CHOSEN_WP_BIN}"
	printf 'socket=%s\n' "${socket_path}"
}

should_filter_known_noise() {
	if [[ "${LOCALWP_WP_FILTER_KNOWN_NOISE:-0}" == "1" ]]; then
		return 0
	fi

	if [[ "${CHOSEN_MODE}" != "default" ]]; then
		return 1
	fi

	php_reports_major_minor "${CHOSEN_PHP_BIN}" "8.5"
}

filter_known_noise() {
	sed \
		-e '/^PHP Deprecated:  Case statements followed by a semicolon (;) are deprecated, use a colon (:) instead in phar:\/\/.*\/vendor\/react\/promise\/src\/functions\.php on line 369$/d' \
		-e '/^Deprecated: Case statements followed by a semicolon (;) are deprecated, use a colon (:) instead in phar:\/\/.*\/vendor\/react\/promise\/src\/functions\.php on line 369$/d' \
		-e '/^PHP Deprecated:  Using null as an array offset is deprecated, use an empty string instead in phar:\/\/.*\/vendor\/wp-cli\/php-cli-tools\/lib\/cli\/Colors\.php on line 95$/d' \
		-e '/^Deprecated: Using null as an array offset is deprecated, use an empty string instead in phar:\/\/.*\/vendor\/wp-cli\/php-cli-tools\/lib\/cli\/Colors\.php on line 95$/d'
}

run_wp_inner() {
	local socket_path=""
	local sock_link=""
	local status=0
	socket_path="$1"
	shift

	if [[ -n "${socket_path}" && -S "${socket_path}" ]]; then
		sock_link="/tmp/_acx_mysqld.$$.$RANDOM.sock"
		rm -f "${sock_link}"
		ln -s "${socket_path}" "${sock_link}"
		if "${CHOSEN_PHP_BIN}" -d "mysqli.default_socket=${sock_link}" "${CHOSEN_WP_BIN}" "$@"; then
			status=0
		else
			status=$?
		fi
		rm -f "${sock_link}"
		return "${status}"
	fi

	"${CHOSEN_PHP_BIN}" "${CHOSEN_WP_BIN}" "$@"
}

run_wp() {
	local socket_path=""
	local status=0
	local stdout_file=""
	local stderr_file=""
	choose_runner
	socket_path="$(discover_socket_or_empty)"

	if ! should_filter_known_noise; then
		exec /bin/bash "${BASH_SOURCE[0]}" --wrapper-no-filter "${socket_path}" "$@"
	fi

	stdout_file="$(mktemp)"
	stderr_file="$(mktemp)"
	if run_wp_inner "${socket_path}" "$@" >"${stdout_file}" 2>"${stderr_file}"; then
		status=0
	else
		status=$?
	fi

	filter_known_noise <"${stdout_file}"
	filter_known_noise <"${stderr_file}" >&2
	rm -f "${stdout_file}" "${stderr_file}"
	return "${status}"
}

COMMAND="${1:-}"

case "${COMMAND}" in
	--print-plan)
		print_plan
		;;
	--wrapper-help)
		show_usage
		;;
	--wrapper-no-filter)
		shift
		socket_path="${1:-}"
		shift || true
		choose_runner
		run_wp_inner "${socket_path}" "$@"
		;;
	--help|-h|help)
		run_wp "$@"
		;;
	"")
		show_usage >&2
		exit 1
		;;
	*)
		run_wp "$@"
		;;
esac
