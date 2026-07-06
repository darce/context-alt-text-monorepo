<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\Repositories\DescriptionUsageRepository;

use function array_reduce;
use function count;
use function get_option;

class DescriptionBudgetService {
	private const MAX_ATTEMPTS_OPTION = 'acx_description_budget_max_attempts';

	private DescriptionUsageRepository $repository;

	public function __construct( ?DescriptionUsageRepository $repository = null ) {
		$this->repository = $repository ?? new DescriptionUsageRepository();
	}

	/**
	 * @return array<string,mixed>
	 */
	public function check_budget(): array {
		$limit = (int) get_option( self::MAX_ATTEMPTS_OPTION, -1 );
		if ( $limit < 0 ) {
			return array(
				'allowed' => true,
				'limit'   => null,
				'used'    => count( $this->repository->all() ),
			);
		}

		$used = count( $this->repository->all() );
		if ( $used >= $limit ) {
			return array(
				'allowed' => false,
				'code'    => 'description_budget_attempt_limit_exceeded',
				'message' => 'Description generation budget attempt limit exceeded.',
				'limit'   => $limit,
				'used'    => $used,
			);
		}

		return array(
			'allowed' => true,
			'limit'   => $limit,
			'used'    => $used,
		);
	}

	/**
	 * @return array<string,mixed>
	 */
	public function record_success(
		int $media_id,
		string $adapter,
		string $provider,
		int $duration_ms,
		bool $cached,
		string $write_status,
		float $cost_amount = 0.0,
		?string $cost_currency = null
	): array {
		return $this->repository->insert(
			array(
				'media_id'      => $media_id,
				'outcome'       => 'success',
				'adapter'       => $adapter,
				'provider'      => $provider,
				'duration_ms'   => $duration_ms,
				'cached'        => $cached,
				'write_status'  => $write_status,
				'cost_amount'   => $cost_amount,
				'cost_currency' => $cost_currency,
			)
		);
	}

	/**
	 * @return array<string,mixed>
	 */
	public function record_error(
		int $media_id,
		string $adapter,
		string $provider,
		string $error_code,
		string $error_message,
		bool $retryable,
		string $source,
		float $cost_amount = 0.0,
		?string $cost_currency = null
	): array {
		return $this->repository->insert(
			array(
				'media_id'      => $media_id,
				'outcome'       => 'failure',
				'adapter'       => $adapter,
				'provider'      => $provider,
				'error_code'    => $error_code,
				'error_message' => $error_message,
				'retryable'     => $retryable,
				'source'        => $source,
				'cost_amount'   => $cost_amount,
				'cost_currency' => $cost_currency,
			)
		);
	}

	/**
	 * @return array<string,mixed>
	 */
	public function usage_summary(): array {
		$rows = $this->repository->all();

		return array(
			'attempts'   => count( $rows ),
			'successes'  => count(
				array_filter(
					$rows,
					static fn ( array $row ): bool => 'success' === ( $row['outcome'] ?? null )
				)
			),
			'failures'   => count(
				array_filter(
					$rows,
					static fn ( array $row ): bool => 'failure' === ( $row['outcome'] ?? null )
				)
			),
			'cost_total' => array_reduce(
				$rows,
				static fn ( float $sum, array $row ): float => $sum + (float) ( $row['cost_amount'] ?? 0.0 ),
				0.0
			),
		);
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function recent_errors( int $limit = 10 ): array {
		return $this->repository->recent_errors( $limit );
	}
}
