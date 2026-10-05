<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\Repositories\DescriptionUsageRepository;

use function array_key_exists;
use function array_reduce;
use function add_option;
use function count;
use function get_option;
use function get_transient;
use function is_array;
use function is_bool;
use function is_int;
use function is_string;
use function set_transient;
use function update_option;
use function wp_cache_delete;
use function wp_generate_uuid4;

class DescriptionBudgetService {
	private const MAX_ATTEMPTS_OPTION = 'acx_description_budget_max_attempts';
	public const DEFAULT_MAX_ATTEMPTS = 1000;
	private const REQUEST_RATE_LIMIT = 30;
	private const REQUEST_RATE_WINDOW_SECONDS = 60;
	private const BUDGET_RESERVATIONS_OPTION = 'acx_description_budget_reservations';
	private const BUDGET_RESERVATION_TTL_SECONDS = 3600;

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
	 * Reserve one attempt before dispatch so concurrent requests cannot all
	 * observe the same remaining site budget.
	 *
	 * @return array<string,mixed>
	 */
	public function reserve_attempt( ?string $operation_id = null ): array {
		$limit = (int) get_option( self::MAX_ATTEMPTS_OPTION, self::DEFAULT_MAX_ATTEMPTS );
		if ( $limit < 0 ) {
			return array(
				'allowed'        => true,
				'limit'          => null,
				'used'           => count( $this->repository->all() ),
				'reservation_id' => null,
			);
		}

		$budget_lock = $this->acquire_budget_lock();
		if ( null === $budget_lock ) {
			return array(
				'allowed' => false,
				'code'    => 'description_budget_reservation_unavailable',
				'message' => 'Description generation budget could not reserve an attempt.',
				'status'  => 503,
			);
		}

		try {
			$limit        = (int) get_option( self::MAX_ATTEMPTS_OPTION, self::DEFAULT_MAX_ATTEMPTS );
			$reservations = $this->active_budget_reservations();
			$usage_rows   = $this->repository->all();
			$used         = count( $usage_rows ) + count( $reservations );
			if ( $limit < 0 ) {
				return array(
					'allowed'        => true,
					'limit'          => null,
					'used'           => count( $this->repository->all() ),
					'reservation_id' => null,
				);
			}

			if ( null !== $operation_id ) {
				foreach ( $usage_rows as $usage_row ) {
					if ( $operation_id === ( $usage_row['operation_id'] ?? null ) ) {
						return array(
							'allowed'        => true,
							'limit'          => $limit,
							'used'           => $used,
							'reservation_id' => null,
						);
					}
				}

				foreach ( $reservations as $existing_reservation_id => $reservation ) {
					if ( is_array( $reservation ) && $operation_id === ( $reservation['operation_id'] ?? null ) ) {
						return array(
							'allowed'        => true,
							'limit'          => $limit,
							'used'           => $used,
							'reservation_id' => $existing_reservation_id,
						);
					}
				}
			}

			if ( $used >= $limit ) {
				return array(
					'allowed' => false,
					'code'    => 'description_budget_attempt_limit_exceeded',
					'message' => 'Description generation budget attempt limit exceeded.',
					'limit'   => $limit,
					'used'    => $used,
				);
			}

			$reservation_id                  = wp_generate_uuid4();
			$reservations[ $reservation_id ] = array(
				'expires_at'   => time() + self::BUDGET_RESERVATION_TTL_SECONDS,
				'dispatched'   => false,
				'operation_id' => $operation_id,
			);
			if ( ! $this->store_budget_reservations( $reservations ) ) {
				return array(
					'allowed' => false,
					'code'    => 'description_budget_reservation_unavailable',
					'message' => 'Description generation budget could not record an attempt reservation.',
					'status'  => 503,
				);
			}

			return array(
				'allowed'        => true,
				'limit'          => $limit,
				'used'           => $used + 1,
				'reservation_id' => $reservation_id,
			);
		} finally {
			$this->release_budget_lock( $budget_lock );
		}
	}

	/**
	 * Persist that dispatch is about to cross the backend boundary. An expired
	 * dispatched reservation continues to count until its operation is settled.
	 */
	public function mark_attempt_dispatched( ?string $reservation_id, ?string $operation_id = null ): bool {
		if ( null === $reservation_id ) {
			return true;
		}

		$budget_lock = $this->acquire_budget_lock();
		if ( null === $budget_lock ) {
			return false;
		}

		try {
			$reservations = $this->active_budget_reservations();
			if ( ! array_key_exists( $reservation_id, $reservations ) ) {
				if ( null !== $operation_id ) {
					foreach ( $this->repository->all() as $usage_row ) {
						if ( $operation_id === ( $usage_row['operation_id'] ?? null ) ) {
							return true;
						}
					}
				}

				return false;
			}

			$reservation = $reservations[ $reservation_id ];
			if ( is_int( $reservation ) ) {
				$reservation = array(
					'expires_at'   => $reservation,
					'dispatched'   => false,
					'operation_id' => null,
				);
			}
			$reservation['dispatched']       = true;
			$reservations[ $reservation_id ] = $reservation;

			return $this->store_budget_reservations( $reservations );
		} finally {
			$this->release_budget_lock( $budget_lock );
		}
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
		?string $cost_currency = null,
		?string $reservation_id = null,
		?string $operation_id = null
	): array {
		return $this->record_usage(
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
				'operation_id'  => $operation_id,
			),
			$reservation_id
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
		?string $cost_currency = null,
		?string $reservation_id = null,
		?string $operation_id = null
	): array {
		return $this->record_usage(
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
				'operation_id'  => $operation_id,
			),
			$reservation_id
		);
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function record_usage( array $row, ?string $reservation_id ): array {
		if ( null === $reservation_id ) {
			return $this->repository->insert( $row );
		}

		$budget_lock = $this->acquire_budget_lock();
		if ( null === $budget_lock ) {
			// Keep the reservation until its expiry. The usage event is still
			// recorded, so a failed cleanup can only temporarily over-count use.
			return $this->repository->insert( $row );
		}

		try {
			$recorded     = $this->repository->insert( $row );
			$reservations = $this->active_budget_reservations();
			if ( isset( $reservations[ $reservation_id ] ) && $this->usage_insert_succeeded( $recorded ) ) {
				unset( $reservations[ $reservation_id ] );
				$this->store_budget_reservations( $reservations );
			}

			return $recorded;
		} finally {
			$this->release_budget_lock( $budget_lock );
		}
	}

	/**
	 * @param array<string,mixed> $recorded
	 */
	private function usage_insert_succeeded( array $recorded ): bool {
		return isset( $recorded['id'] );
	}

	/**
	 * Serialize admission and finalization across database connections. MySQL
	 * releases the named lock if the worker's connection closes unexpectedly.
	 */
	private function acquire_budget_lock(): ?string {
		global $wpdb;
		if (
			! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'get_var' )
		) {
			return null;
		}

		$lock_name = $this->budget_lock_name();
		$acquired = $wpdb->get_var( $wpdb->prepare( 'SELECT GET_LOCK(%s, %d)', $lock_name, 1 ) );
		return '1' === (string) $acquired ? $lock_name : null;
	}

	private function release_budget_lock( string $lock_name ): void {
		global $wpdb;
		$wpdb->get_var( $wpdb->prepare( 'SELECT RELEASE_LOCK(%s)', $lock_name ) );
	}

	private function budget_lock_name(): string {
		global $wpdb;
		$site_prefix = isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ? $wpdb->prefix : 'default';
		return 'acx_budget_lock_' . md5( $site_prefix );
	}

	/**
	 * @return array<string,int|array<string,mixed>>
	 */
	private function active_budget_reservations(): array {
		// Another worker may have written while this worker waited for the lock.
		// Discard local option caches before reading the durable reservation map.
		wp_cache_delete( self::BUDGET_RESERVATIONS_OPTION, 'options' );
		wp_cache_delete( 'notoptions', 'options' );
		$reservations = get_option( self::BUDGET_RESERVATIONS_OPTION, array() );
		if ( ! is_array( $reservations ) ) {
			return array();
		}

		$operation_ids = array();
		$changed       = false;
		$now           = time();
		foreach ( $reservations as $reservation_id => $reservation ) {
			if ( ! is_string( $reservation_id ) ) {
				unset( $reservations[ $reservation_id ] );
				$changed = true;
				continue;
			}

			if ( is_int( $reservation ) ) {
				$expires_at = $reservation;
				$dispatched = false;
				$operation_id = null;
			} elseif (
				is_array( $reservation )
				&& is_int( $reservation['expires_at'] ?? null )
				&& is_bool( $reservation['dispatched'] ?? null )
				&& ( null === ( $reservation['operation_id'] ?? null ) || is_string( $reservation['operation_id'] ) )
			) {
				$expires_at   = $reservation['expires_at'];
				$dispatched   = $reservation['dispatched'];
				$operation_id = $reservation['operation_id'];
			} else {
				unset( $reservations[ $reservation_id ] );
				$changed = true;
				continue;
			}

			if ( $dispatched && is_string( $operation_id ) ) {
				$operation_ids[ $operation_id ] = true;
			}

			if ( $expires_at <= $now && ! $dispatched ) {
				unset( $reservations[ $reservation_id ] );
				$changed = true;
			}
		}

		if ( count( $operation_ids ) > 0 ) {
			$settled_operation_ids = array();
			foreach ( $this->repository->all() as $usage_row ) {
				$settled_operation_id = $usage_row['operation_id'] ?? null;
				if ( is_string( $settled_operation_id ) && isset( $operation_ids[ $settled_operation_id ] ) ) {
					$settled_operation_ids[ $settled_operation_id ] = true;
				}
			}

			foreach ( $reservations as $reservation_id => $reservation ) {
				if (
					is_array( $reservation )
					&& is_string( $reservation['operation_id'] ?? null )
					&& isset( $settled_operation_ids[ $reservation['operation_id'] ] )
				) {
					unset( $reservations[ $reservation_id ] );
					$changed = true;
				}
			}
		}

		if ( $changed ) {
			$this->store_budget_reservations( $reservations );
		}

		return $reservations;
	}

	/**
	 * @param array<string,int|array<string,mixed>> $reservations
	 */
	private function store_budget_reservations( array $reservations ): bool {
		if ( false === get_option( self::BUDGET_RESERVATIONS_OPTION, false ) ) {
			return add_option( self::BUDGET_RESERVATIONS_OPTION, $reservations, '', false );
		}

		// update_option also returns false when the value is already identical.
		return update_option( self::BUDGET_RESERVATIONS_OPTION, $reservations, false )
			|| get_option( self::BUDGET_RESERVATIONS_OPTION, false ) === $reservations;
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
