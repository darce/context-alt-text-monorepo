<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\Repositories\DescriptionUsageRepository;

use function array_reduce;
use function count;
use function get_option;

class DescriptionBudgetService {
	private const MAX_ATTEMPTS_OPTION = 'acx_description_budget_max_attempts';
	public const DEFAULT_MAX_ATTEMPTS = 1000;
	private const REQUEST_RATE_LIMIT = 30;
	private const REQUEST_RATE_WINDOW_SECONDS = 60;

	private DescriptionUsageRepository $repository;

	public function __construct( ?DescriptionUsageRepository $repository = null ) {
		$this->repository = $repository ?? new DescriptionUsageRepository();
	}

	/**
	 * @return array<string,mixed>
	 */
	public function check_budget(): array {
		$limit = (int) get_option( self::MAX_ATTEMPTS_OPTION, self::DEFAULT_MAX_ATTEMPTS );
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
	 * Enforce a per-user fixed-window limit for expensive recognition requests.
	 *
	 * The counter update runs under a MySQL named lock so concurrent requests
	 * cannot lose increments and exceed the configured burst limit.
	 *
	 * @return array<string,mixed>
	 */
	public function check_request_rate_limit( int $user_id ): array {
		if ( $user_id <= 0 ) {
			return array(
				'allowed' => false,
				'code'    => 'recognition_rate_limit_unavailable',
				'message' => 'Recognition request rate limit could not identify the caller.',
				'status'  => 503,
			);
		}

		$window_number = intdiv( time(), self::REQUEST_RATE_WINDOW_SECONDS );
		$transient_key = 'acx_recognition_rate_' . md5( $user_id . ':' . $window_number );
		$lock_name     = 'acx_rl_' . md5( $transient_key );
		if ( ! $this->acquire_rate_limit_lock( $lock_name ) ) {
			return array(
				'allowed' => false,
				'code'    => 'recognition_rate_limit_unavailable',
				'message' => 'Recognition request rate limit is temporarily unavailable.',
				'status'  => 503,
			);
		}

		try {
			$used        = (int) get_transient( $transient_key );
			$window_ends = ( $window_number + 1 ) * self::REQUEST_RATE_WINDOW_SECONDS;
			$retry_after = max( 1, $window_ends - time() );

			if ( $used >= self::REQUEST_RATE_LIMIT ) {
				return array(
					'allowed'     => false,
					'code'        => 'recognition_rate_limit_exceeded',
					'message'     => 'Recognition request rate limit exceeded.',
					'status'      => 429,
					'limit'       => self::REQUEST_RATE_LIMIT,
					'used'        => $used,
					'retry_after' => $retry_after,
				);
			}

			if ( ! set_transient( $transient_key, $used + 1, $retry_after ) ) {
				return array(
					'allowed' => false,
					'code'    => 'recognition_rate_limit_unavailable',
					'message' => 'Recognition request rate limit could not be recorded.',
					'status'  => 503,
				);
			}

			return array(
				'allowed' => true,
				'limit'   => self::REQUEST_RATE_LIMIT,
				'used'    => $used + 1,
			);
		} finally {
			$this->release_rate_limit_lock( $lock_name );
		}
	}

	private function acquire_rate_limit_lock( string $lock_name ): bool {
		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return false;
		}

		$acquired = $wpdb->get_var( $wpdb->prepare( 'SELECT GET_LOCK(%s, %d)', $lock_name, 1 ) );
		return '1' === (string) $acquired;
	}

	private function release_rate_limit_lock( string $lock_name ): void {
		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return;
		}

		$wpdb->get_var( $wpdb->prepare( 'SELECT RELEASE_LOCK(%s)', $lock_name ) );
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
