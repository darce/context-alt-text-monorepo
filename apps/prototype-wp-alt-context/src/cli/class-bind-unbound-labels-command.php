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
	 * Idempotent. Processes bounded batches and exits non-zero after a stall
	 * (a batch that binds nothing).
	 *
	 * ## OPTIONS
	 *
	 * [--batch-size=<number>]
	 * : Clusters per batch. Default 100, max 100.
	 *
	 * ## EXAMPLES
	 *
	 *     wp acx bind-unbound-labels
	 *     wp acx bind-unbound-labels --batch-size=50
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

		$tenant_id = TenantIdentity::resolve()['value'];
		$result    = $this->service->backfill_tenant( $tenant_id, $batch_size );

		\WP_CLI::log(
			sprintf(
				'Bound %d person(s) from %d unbound human-labelled cluster(s).',
				(int) $result['bound'],
				(int) $result['examined']
			)
		);

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
