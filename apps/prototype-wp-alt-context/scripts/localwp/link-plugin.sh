#!/usr/bin/env bash
set -euo pipefail

show_usage() {
	cat <<'USAGE'
Usage:
  bash apps/prototype-wp-alt-context/scripts/localwp/link-plugin.sh \
    --wp-path /path/to/wordpress/app/public \
    [--plugin-source /stable/path/to/apps/prototype-wp-alt-context] \
    [--overwrite] \
    [--allow-worktree-source] \
    [--dry-run]

Purpose:
  Create or refresh a LocalWP-facing symlink at:
    <wp-path>/wp-content/plugins/alt-context

Safety defaults:
  - Refuses linked git worktree sources by default. Task worktrees are ephemeral
    and can disappear during normal branch cleanup.
  - Refuses to replace an existing target unless --overwrite is passed.
  - When replacing a target, moves the prior path aside to a timestamped backup
    instead of deleting it.

Recommended usage:
  - Active development: point LocalWP at a stable standalone checkout.
  - Release/gate verification: use the ZIP packaging workflow instead of a
    symlinked plugin install.
USAGE
}

PLUGIN_SLUG="alt-context"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PLUGIN_SOURCE="$(cd "${SCRIPT_DIR}/../.." && pwd)"

WP_PATH=""
PLUGIN_SOURCE="${DEFAULT_PLUGIN_SOURCE}"
OVERWRITE=0
ALLOW_WORKTREE_SOURCE=0
DRY_RUN=0

while (($# > 0)); do
	case "$1" in
		--wp-path)
			WP_PATH="${2:-}"
			shift 2
			;;
		--plugin-source)
			PLUGIN_SOURCE="${2:-}"
			shift 2
			;;
		--overwrite)
			OVERWRITE=1
			shift
			;;
		--allow-worktree-source)
			ALLOW_WORKTREE_SOURCE=1
			shift
			;;
		--dry-run)
			DRY_RUN=1
			shift
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
	echo "ERROR: --wp-path is required." >&2
	show_usage >&2
	exit 1
fi

SOURCE_REAL="$(cd "${PLUGIN_SOURCE}" && pwd)"
WP_REAL="$(cd "${WP_PATH}" && pwd)"
PLUGIN_FILE="${SOURCE_REAL}/alt-context.php"
TARGET_DIR="${WP_REAL}/wp-content/plugins"
TARGET_PATH="${TARGET_DIR}/${PLUGIN_SLUG}"

if [[ ! -f "${WP_REAL}/wp-load.php" ]]; then
	echo "ERROR: Invalid --wp-path '${WP_REAL}' (missing wp-load.php)." >&2
	exit 1
fi

if [[ ! -f "${PLUGIN_FILE}" ]]; then
	echo "ERROR: Invalid --plugin-source '${SOURCE_REAL}' (missing alt-context.php)." >&2
	exit 1
fi

is_linked_worktree_source() {
	local candidate="$1"
	local repo_root=""
	if repo_root="$(git -C "${candidate}" rev-parse --show-toplevel 2>/dev/null)"; then
		if [[ -f "${repo_root}/.git" ]]; then
			return 0
		fi
	fi
	return 1
}

if [[ "${ALLOW_WORKTREE_SOURCE}" -ne 1 ]] && is_linked_worktree_source "${SOURCE_REAL}"; then
	echo "ERROR: Refusing linked-worktree source by default:" >&2
	echo "  ${SOURCE_REAL}" >&2
	echo >&2
	echo "This looks like a git worktree checkout, which is fragile for LocalWP." >&2
	echo "Use a stable standalone checkout for day-to-day symlink installs, or" >&2
	echo "re-run with --allow-worktree-source only if you are intentionally opting in." >&2
	exit 1
fi

mkdir -p "${TARGET_DIR}"

if [[ -L "${TARGET_PATH}" ]]; then
	CURRENT_TARGET="$(readlink "${TARGET_PATH}")"
	CURRENT_REAL="$(cd "$(dirname "${TARGET_PATH}")" && cd "${CURRENT_TARGET}" 2>/dev/null && pwd || true)"
	if [[ -n "${CURRENT_REAL}" ]] && [[ "${CURRENT_REAL}" == "${SOURCE_REAL}" ]]; then
		echo "LocalWP plugin symlink already points at ${SOURCE_REAL}"
		exit 0
	fi
fi

if [[ -e "${TARGET_PATH}" || -L "${TARGET_PATH}" ]]; then
	if [[ "${OVERWRITE}" -ne 1 ]]; then
		echo "ERROR: Target already exists at ${TARGET_PATH}" >&2
		echo "Re-run with --overwrite to move the current target aside and replace it." >&2
		exit 1
	fi
fi

BACKUP_PATH=""
if [[ -e "${TARGET_PATH}" || -L "${TARGET_PATH}" ]]; then
	TIMESTAMP="$(date +%Y%m%d%H%M%S)"
	BACKUP_PATH="${TARGET_PATH}.backup.${TIMESTAMP}"
fi

echo "Plugin source : ${SOURCE_REAL}"
echo "WordPress root: ${WP_REAL}"
echo "Target path   : ${TARGET_PATH}"
if [[ -n "${BACKUP_PATH}" ]]; then
	echo "Backup path   : ${BACKUP_PATH}"
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
	echo "Dry run only; no filesystem changes made."
	exit 0
fi

if [[ -n "${BACKUP_PATH}" ]]; then
	mv "${TARGET_PATH}" "${BACKUP_PATH}"
fi

ln -s "${SOURCE_REAL}" "${TARGET_PATH}"

echo
echo "Linked LocalWP plugin:"
echo "  ${TARGET_PATH} -> ${SOURCE_REAL}"
echo
echo "Use ZIP packaging instead of this symlink for release/gate verification:"
echo "  bash apps/prototype-wp-alt-context/scripts/release/package-plugin.sh"
