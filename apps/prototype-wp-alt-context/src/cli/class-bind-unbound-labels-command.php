<?php

declare(strict_types=1);

namespace AltContext\Cli;

require_once dirname( __DIR__ ) . '/api/services/class-person-label-backfill-service.php';

use AltContext\Api\Services\PersonLabelBackfillService;
use AltContext\Api\TenantIdentity;

use function class_exists;
use function is_numeric;
use function max;
use function min;
use function sprintf;

/**
 * Bind persons for existing human-labelled, person-less clusters.
 */
class BindUnboundLabelsCommand extends \WP_CLI_Command {

	private PersonLabelBackfillService $service;

	public function __construct( ?PersonLabelBackfillService $service = null ) {
		$this->service = $service ?? new PersonLabelBackfillService();
	}

	/**
	 * Bind roster persons for human-labelled clusters that have no person_id.
	 *
	 * Idempotent. Processes bounded batches. Exits non-zero after a stall.
	 *
	 * ## OPTIONS
	 *
	 * [--batch-size=<number>]
	 * : Clusters per batch. Default 100, max 100.
	 *
	 * [--dry-run]
	 * : Examine rows without writing person_id.
	 *
	 * ## EXAMPLES
	 *
	 *     wp acx bind-unbound-labels
	 *     wp acx bind-unbound-labels --batch-size=50
	 *     wp acx bind-unbound-labels --dry-run
	 *
	 * @param string[]             $args
	 * @param array<string,mixed>  $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! class_exists( '\\WP_CLI' ) ) {
			return;
		}

		$batch_size = PersonLabelBackfillService::BATCH_SIZE;
		if ( isset( $assoc_args['batch-size'] ) && is_numeric( $assoc_args['batch-size'] ) ) {
			$batch_size = max( 1, min( PersonLabelBackfillService::BATCH_SIZE, (int) $assoc_args['batch-size'] ) );
		}

		$dry_run   = isset( $assoc_args['dry-run'] );
		$tenant_id = TenantIdentity::resolve()['value'];
		$result    = $this->service->backfill_tenant( $tenant_id, $batch_size, $dry_run );

		if ( $result['empty'] ) {
			\WP_CLI::log( 'Tenant has no unbound human-labelled clusters.' );
			\WP_CLI::success( 'Unbound-label backfill complete.' );
			return;
		}

		\WP_CLI::log(
			sprintf(
				'Bound %d cluster(s) to %d person(s), %d created',
				(int) $result['bound'],
				(int) $result['persons'],
				(int) $result['created']
			)
		);

		if ( $result['collisions'] > 0 ) {
			\WP_CLI::warning(
				sprintf( 'Name collisions created %d distinct person(s).', (int) $result['collisions'] )
			);
		}

		if ( $dry_run ) {
			\WP_CLI::success( 'Dry-run complete. No rows written.' );
			return;
		}

		if ( $result['stalled'] ) {
			\WP_CLI::error(
				sprintf(
					'Stopped after %d no-progress batches (rg-007).',
					(int) $result['stalls']
				)
			);
		}

		\WP_CLI::success( 'Unbound-label backfill complete.' );
	}
}
