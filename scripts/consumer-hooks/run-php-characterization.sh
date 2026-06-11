#!/bin/sh
# Consumer-local merge-result gate: run all three golden characterization suites
# against the current tree (the resolved merge commit at push/CI time).

set -eu

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "run-php-characterization: not inside a git repository" >&2
    exit 1
fi

PLUGIN_DIR="$REPO_ROOT/apps/prototype-wp-alt-context"
FILTER='AnalysisJobsControllerCharacterizationTest|ClusterMutationsCharacterizationTest|ClustersControllerCharacterizationTest'

if [ ! -x "$PLUGIN_DIR/vendor/bin/phpunit" ]; then
    echo "run-php-characterization: missing phpunit; run composer install in $PLUGIN_DIR" >&2
    exit 1
fi

cd "$PLUGIN_DIR"
exec vendor/bin/phpunit --filter "$FILTER"