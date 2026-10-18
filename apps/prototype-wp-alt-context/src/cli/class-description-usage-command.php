<?php

declare(strict_types=1);

namespace AltContext\Cli;

require_once __DIR__ . '/../api/services/class-description-budget-service.php';

use AltContext\Api\Services\DescriptionBudgetService;
use function class_exists;
use function count;
use function sprintf;

/**
 * Report description generation usage and recent provider/client errors.
 *
 * @package AltContext\Cli
 */
class DescriptionUsageCommand extends \WP_CLI_Command {
	private DescriptionBudgetService $budget_service;

	public function __construct( ?DescriptionBudgetService $budget_service = null ) {
		$this->budget_service = $budget_service ?? new DescriptionBudgetService();
	}

	/**
	 * Print usage totals and recent errors.
	 *
	 * ## EXAMPLES
	 *
	 *     wp acx description-usage
	 *
	 * @param string[] $args
	 * @param array<string,mixed> $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! class_exists( '\\WP_CLI' ) ) {
			return;
		}

		$usage  = $this->budget_service->usage_summary();
		$errors = $this->budget_service->recent_errors( 5 );

		\WP_CLI::log(
			sprintf(
				'attempts=%d successes=%d failures=%d cost_total=%.4f',
				(int) ( $usage['attempts'] ?? 0 ),
				(int) ( $usage['successes'] ?? 0 ),
				(int) ( $usage['failures'] ?? 0 ),
				(float) ( $usage['cost_total'] ?? 0.0 )
			)
		);

		if ( array() === $errors ) {
			\WP_CLI::log( 'recent_errors=0' );
		}

		foreach ( $errors as $error ) {
			\WP_CLI::log(
				sprintf(
					'error media_id=%d code=%s retryable=%s message=%s',
					(int) ( $error['media_id'] ?? 0 ),
					(string) ( $error['error_code'] ?? '' ),
					! empty( $error['retryable'] ) ? 'yes' : 'no',
					(string) ( $error['error_message'] ?? '' )
				)
			);
		}

		\WP_CLI::success( sprintf( 'Description usage reported. recent_errors=%d', count( $errors ) ) );
	}
}
