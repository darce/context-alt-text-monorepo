<?php

declare(strict_types=1);

namespace ContextAltText\Roster;

use ContextAltText\Domain\Roster\RosterService;
use WP_CLI;
use WP_CLI_Command;
use function sprintf;
use function get_option;
use function is_array;

class RosterCli extends WP_CLI_Command
{
    private RosterService $service;

    public function __construct(RosterService $service)
    {
        $this->service = $service;
    }

    /**
     * Display roster sync status metrics.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster status
     */
    public function status(array $args, array $assocArgs): void
    {
        unset($args, $assocArgs);

        $state = get_option('cat_roster_sync_state');

        if (!is_array($state)) {
            $state = [
                'lastSyncAt' => null,
                'created' => 0,
                'updated' => 0,
                'deleted' => 0,
                'errors' => 0,
                'conflicts' => 0,
            ];
        }

        WP_CLI::log('Roster Sync Metrics:');
        WP_CLI::log(sprintf('  Last Sync: %s', $state['lastSyncAt'] ?? 'never'));
        WP_CLI::log(sprintf('  Created: %d', (int) ($state['created'] ?? 0)));
        WP_CLI::log(sprintf('  Updated: %d', (int) ($state['updated'] ?? 0)));
        WP_CLI::log(sprintf('  Deleted: %d', (int) ($state['deleted'] ?? 0)));
        WP_CLI::log(sprintf('  Conflicts: %d', (int) ($state['conflicts'] ?? 0)));
        WP_CLI::log(sprintf('  Errors: %d', (int) ($state['errors'] ?? 0)));

        if (isset($state['lastError']) && is_array($state['lastError'])) {
            WP_CLI::log(sprintf('  Last Error: %s', $state['lastError']['message'] ?? 'Unknown'));
        }

        WP_CLI::success('Roster status fetched.');
    }

    /**
     * Trigger a roster sync from the remote service.
     *
     * ## EXAMPLES
     *
     *     wp cat-roster sync
     */
    public function sync(array $args, array $assocArgs): void
    {
        unset($args, $assocArgs);

        $result = $this->service->syncFromRemote();

        if ($result) {
            WP_CLI::success('Roster sync completed.');
        } else {
            WP_CLI::warning('Roster sync did not report any changes.');
        }
    }
}
