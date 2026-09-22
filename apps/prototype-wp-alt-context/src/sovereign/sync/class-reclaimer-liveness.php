<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use DateTimeInterface;

use function add_option;
use function delete_option;
use function do_action;
use function function_exists;
use function get_option;
use function gmdate;
use function hash;
use function is_array;
use function is_callable;
use function in_array;
use function is_numeric;
use function is_string;
use function max;
use function method_exists;
use function microtime;
use function preg_replace;
use function random_int;
use function strtotime;
use function time;
use function trim;
use function update_option;
use function wp_generate_uuid4;

/**
 * Durable, tenant-scoped purge history and the short lease used by reclaimer runs.
 *
 * History lives in one non-autoloaded option per tenant.  The lease deliberately
 * does not use the option API: claim is one conditional INSERT/UPDATE statement
 * against the real wp_options table, and release compares the owner token in SQL.
 */
class ReclaimerLiveness {
	public const STATE_NEVER_RUN = 'never_run';
	public const STATE_HEALTHY = 'healthy';
	public const STATE_OVERDUE = 'overdue';
	public const STATE_BREACH = 'breach';

	public const SCHEDULER_ACTION_SCHEDULER = 'action_scheduler';
	public const SCHEDULER_WP_CRON = 'wp_cron';

	public const OUTCOME_SUCCESS = 'success';
	public const OUTCOME_FAILED = 'failed';
	public const OUTCOME_LOCK_CONTENDED = 'lock_contended';

	public const ACTION_SCHEDULER_PERIOD_SECONDS = 3600;
	public const WP_CRON_PERIOD_SECONDS = 86400;
	public const INLINE_PURGE_BATCH_SIZE = 100;

	private const OPTION_PREFIX = 'acx_reclaimer_liveness_';
	private const PURGE_SCHEDULER_OPTION = 'acx_reclaimer_purge_scheduler';
	private const LEASE_OPTION_PREFIX = 'acx_reclaimer_lease_';
	private const TENANT_INDEX_OPTION = 'acx_reclaimer_tenant_index';
	private const LEASE_SECONDS = 300;
	private const WRITE_STATUS_COMMITTED = 'committed';
	private const WRITE_STATUS_COMMITTED_WITHOUT_FENCE = 'committed_without_fence';
	private const WRITE_STATUS_FENCE_REJECTED = 'fence_rejected';
	private const WRITE_STATUS_NO_OP = 'no_op';

	/** @var callable():int|DateTimeInterface|string|null */
	private $clock;

	/** @var array<string,array<string,string>> */
	private array $lease_values = array();

	/** @var array<string,array<string,int>> */
	private array $lease_tokens = array();

	/** @var array<string,string|null> */
	private array $active_leases = array();

	/** @var int Fallback only for adapters that cannot read back the claimed option. */
	private static int $fallback_fencing_token = 0;

	/**
	 * @param callable():int|DateTimeInterface|string|null $clock
	 */
	public function __construct( $clock = null ) {
		$this->clock = is_callable( $clock ) ? $clock : static fn (): int => time();
	}

	/**
	 * Return the wire-contract shape for one tenant. State is derived from the
	 * last committed success at read time, so changing the clock is sufficient
	 * to cross the overdue and breach thresholds in tests and workers.
	 *
	 * @return array{
	 *   state:string,
	 *   scheduler_mode:string,
	 *   effective_period_seconds:int,
	 *   last_attempt_at:?string,
	 *   last_success_at:?string,
	 *   last_outcome:?string,
	 *   last_purged_count:?int,
	 *   backlog_remaining:?int,
	 *   backlog_oldest_age_seconds:?int,
	 *   batch_cap_reached:bool
	 * }
	 */
	public function read( string $tenant_id, ?string $scheduler_mode = null ): array {
		$tenant_id = $this->normalize_tenant_id( $tenant_id );
		$stored = '' === $tenant_id ? array() : $this->load_state( $tenant_id );
		$mode = $this->resolve_scheduler_mode( $stored['scheduler_mode'] ?? null, $scheduler_mode );
		$period = is_numeric( $stored['effective_period_seconds'] ?? null ) && (int) $stored['effective_period_seconds'] > 0
			? (int) $stored['effective_period_seconds']
			: $this->effective_period_seconds( $mode );

		$last_attempt_at = $this->normalize_timestamp( $stored['last_attempt_at'] ?? null );
		$last_success_at = $this->normalize_timestamp( $stored['last_success_at'] ?? null );
		$state = self::STATE_NEVER_RUN;
		if ( null !== $last_success_at ) {
			$age = max( 0, $this->now() - $this->timestamp_to_epoch( $last_success_at ) );
			if ( $age > ( 2 * $period ) ) {
				$state = self::STATE_BREACH;
			} elseif ( $age > $period ) {
				$state = self::STATE_OVERDUE;
			} else {
				$state = self::STATE_HEALTHY;
			}
		}

		return array(
			'state' => $state,
			'scheduler_mode' => $mode,
			'effective_period_seconds' => $period,
			'last_attempt_at' => $last_attempt_at,
			'last_success_at' => $last_success_at,
			'last_outcome' => $this->normalize_outcome( $stored['last_outcome'] ?? null ),
			'last_purged_count' => $this->nullable_non_negative_int( $stored['last_purged_count'] ?? null ),
			'backlog_remaining' => $this->nullable_non_negative_int( $stored['backlog_remaining'] ?? null ),
			'backlog_oldest_age_seconds' => $this->nullable_non_negative_int( $stored['backlog_oldest_age_seconds'] ?? null ),
			'batch_cap_reached' => ! empty( $stored['batch_cap_reached'] ),
		);
	}

	/**
	 * Whether inline recovery is warranted for this tenant.
	 */
	public function should_run_inline( string $tenant_id ): bool {
		$state = $this->read( $tenant_id );
		return in_array( $state['state'], array( self::STATE_OVERDUE, self::STATE_BREACH ), true )
			|| true === $state['batch_cap_reached'];
	}

	/**
	 * Stamp the beginning of an attempt. A worker that dies after this point is
	 * still represented as a failed/incomplete attempt until a committed success
	 * replaces the outcome.
	 */
	public function record_attempt( string $tenant_id, ?string $scheduler_mode = null ): void {
		$this->write_state(
			$tenant_id,
			array(
				'last_attempt_at' => $this->now_iso8601(),
				'last_outcome' => self::OUTCOME_FAILED,
				'scheduler_mode' => $scheduler_mode,
			)
		);
	}

	/**
	 * Record a committed purge. This is the only method that advances success.
	 */
	public function record_success(
		string $tenant_id,
		int $purged_count,
		?int $backlog_remaining = null,
		?int $backlog_oldest_age_seconds = null,
		bool $batch_cap_reached = false,
		?string $scheduler_mode = null
	): void {
		$this->write_state(
			$tenant_id,
			array(
				'last_attempt_at' => $this->now_iso8601(),
				'last_success_at' => $this->now_iso8601(),
				'last_outcome' => self::OUTCOME_SUCCESS,
				'last_purged_count' => max( 0, $purged_count ),
				'backlog_remaining' => $this->nullable_non_negative_int( $backlog_remaining ),
				'backlog_oldest_age_seconds' => $this->nullable_non_negative_int( $backlog_oldest_age_seconds ),
				'batch_cap_reached' => $batch_cap_reached,
				'scheduler_mode' => $scheduler_mode,
			)
		);
	}

	/**
	 * Record a failed attempt without changing the previous committed success.
	 */
	public function record_failure( string $tenant_id, ?string $scheduler_mode = null ): void {
		$stored = $this->load_state( $this->normalize_tenant_id( $tenant_id ) );
		$this->write_state(
			$tenant_id,
			array(
				'last_attempt_at' => $this->now_iso8601(),
				'last_outcome' => self::OUTCOME_FAILED,
				// Preserve the last committed metrics. A failed/rolled-back attempt
				// must not erase the cap signal that can trigger the next recovery.
				'last_purged_count' => $stored['last_purged_count'] ?? null,
				'backlog_remaining' => $stored['backlog_remaining'] ?? null,
				'backlog_oldest_age_seconds' => $stored['backlog_oldest_age_seconds'] ?? null,
				'batch_cap_reached' => ! empty( $stored['batch_cap_reached'] ),
				'scheduler_mode' => $scheduler_mode,
			)
		);
	}

	/**
	 * Record contention and leave all prior success/metrics intact.
	 */
	public function record_lock_contended( string $tenant_id, ?string $scheduler_mode = null ): void {
		$this->write_state(
			$tenant_id,
			array(
				'last_attempt_at' => $this->now_iso8601(),
				'last_outcome' => self::OUTCOME_LOCK_CONTENDED,
				'scheduler_mode' => $scheduler_mode,
			)
		);
	}

	/**
	 * Claim a tenant lease with one conditional SQL statement.
	 *
	 * @return string|false|null Owner token on success, false on adapter/query
	 *                           failure, null when another live owner wins.
	 */
	public function claim( string $tenant_id ): string|false|null {
		$tenant_id = $this->normalize_tenant_id( $tenant_id );
		if ( '' === $tenant_id ) {
			return false;
		}

		global $wpdb;
		if (
			! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! isset( $wpdb->options )
			|| ! is_string( $wpdb->options )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'query' )
		) {
			return false;
		}

		$owner = function_exists( 'wp_generate_uuid4' )
			? (string) wp_generate_uuid4()
			: hash( 'sha256', $tenant_id . '|' . microtime( true ) . '|' . random_int( 0, PHP_INT_MAX ) );
		$fallback_token = ++self::$fallback_fencing_token;
		$expires_at = $this->now() + self::LEASE_SECONDS;
		$lease_value = $owner . '|' . $fallback_token . '|' . $expires_at;
		$option_name = $this->lease_option_name( $tenant_id );
		$query = $wpdb->prepare(
			'INSERT INTO %i (option_name, option_value, autoload) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE option_value = IF(CAST(SUBSTRING_INDEX(option_value, %s, -1) AS UNSIGNED) <= %d, CONCAT(%s, %s, CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(option_value, %s, 2), %s, -1) AS UNSIGNED) + 1, %s, %d), option_value)',
			$wpdb->options,
			$option_name,
			$lease_value,
			'no',
			'|',
			$this->now(),
			$owner,
			'|',
			'|',
			'|',
			'|',
			$expires_at
		);
		$result = $wpdb->query( $query );
		if ( false === $result || null === $result ) {
			return false;
		}

		$affected = is_numeric( $result ) ? (int) $result : (int) ( $wpdb->rows_affected ?? 0 );
		if ( $affected <= 0 ) {
			return null;
		}

		$this->register_tenant_key( $this->safe_tenant_key( $tenant_id ) );

		$stored_lease_value = $this->read_lease_value( $wpdb, $option_name );
		if ( is_string( $stored_lease_value ) ) {
			$parsed_lease = $this->parse_lease_value( $stored_lease_value );
			if ( ! is_array( $parsed_lease ) || $owner !== $parsed_lease['owner'] ) {
				return null;
			}

			$lease_value = $stored_lease_value;
			$fencing_token = $parsed_lease['fencing_token'];
		} else {
			$fencing_token = $fallback_token;
		}

		$this->lease_values[ $tenant_id ][ $owner ] = $lease_value;
		$this->lease_tokens[ $tenant_id ][ $owner ] = $fencing_token;
		$this->active_leases[ $tenant_id ] = $owner;
		return $owner;
	}

	/**
	 * Release only the lease held by the supplied owner token.
	 */
	public function release( string $tenant_id, string $owner ): bool {
		$tenant_id = $this->normalize_tenant_id( $tenant_id );
		$owner = trim( $owner );
		if ( '' === $tenant_id || '' === $owner ) {
			return false;
		}

		global $wpdb;
		if (
			! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! isset( $wpdb->options )
			|| ! is_string( $wpdb->options )
			|| ! method_exists( $wpdb, 'prepare' )
		) {
			return false;
		}

		$option_name = $this->lease_option_name( $tenant_id );
		$lease_value = $this->lease_values[ $tenant_id ][ $owner ] ?? null;
		$fencing_token = $this->lease_tokens[ $tenant_id ][ $owner ] ?? null;
		if ( ! is_string( $lease_value ) || ! is_int( $fencing_token ) || ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		$query = $wpdb->prepare(
			'UPDATE %i SET option_value = %s WHERE option_name = %s AND option_value = %s AND BINARY option_value = %s',
			$wpdb->options,
			$owner . '|' . $fencing_token . '|0',
			$option_name,
			$lease_value,
			$lease_value
		);
		$result = $wpdb->query( $query );
		$affected = is_numeric( $result ) ? (int) $result : (int) ( $wpdb->rows_affected ?? 0 );
		if ( $affected <= 0 ) {
			return false;
		}

		unset( $this->lease_values[ $tenant_id ][ $owner ] );
		unset( $this->lease_tokens[ $tenant_id ][ $owner ] );
		if ( ( $this->active_leases[ $tenant_id ] ?? null ) === $owner ) {
			$this->active_leases[ $tenant_id ] = null;
		}

		return $affected > 0;
	}

	public function current_scheduler_mode( ?string $booked_scheduler_mode = null ): string {
		if ( self::SCHEDULER_ACTION_SCHEDULER === $booked_scheduler_mode || self::SCHEDULER_WP_CRON === $booked_scheduler_mode ) {
			return $booked_scheduler_mode;
		}

		// Capability is not evidence of a successful booking. Callers that have
		// just scheduled work must pass the mode returned by that booking path.
		return self::SCHEDULER_WP_CRON;
	}

	public function record_booked_scheduler_mode( string $scheduler_mode ): void {
		if ( self::SCHEDULER_ACTION_SCHEDULER !== $scheduler_mode && self::SCHEDULER_WP_CRON !== $scheduler_mode ) {
			return;
		}

		update_option( self::PURGE_SCHEDULER_OPTION, $scheduler_mode, false );
	}

	public function booked_scheduler_mode(): ?string {
		$scheduler_mode = get_option( self::PURGE_SCHEDULER_OPTION );
		if ( self::SCHEDULER_ACTION_SCHEDULER === $scheduler_mode || self::SCHEDULER_WP_CRON === $scheduler_mode ) {
			return $scheduler_mode;
		}

		return null;
	}

	/**
	 * Remove all reclaimer options recorded in the tenant index.
	 *
	 * @return int Number of options that were present and removed.
	 */
	public function purge_all_options(): int {
		$registered_keys = get_option( self::TENANT_INDEX_OPTION, array() );
		$tenant_keys = array();
		if ( is_array( $registered_keys ) ) {
			foreach ( $registered_keys as $registered_key ) {
				if ( is_string( $registered_key ) && '' !== $registered_key && ! in_array( $registered_key, $tenant_keys, true ) ) {
					$tenant_keys[] = $registered_key;
				}
			}
		}

		$removed = 0;
		$missing = new \stdClass();
		foreach ( $tenant_keys as $tenant_key ) {
			$state_option = self::OPTION_PREFIX . $tenant_key;
			if ( $missing !== get_option( $state_option, $missing ) ) {
				delete_option( $state_option );
				++$removed;
			}

			$lease_option = self::LEASE_OPTION_PREFIX . $tenant_key;
			if ( $missing !== get_option( $lease_option, $missing ) ) {
				delete_option( $lease_option );
				++$removed;
			}
		}

		if ( $missing !== get_option( self::PURGE_SCHEDULER_OPTION, $missing ) ) {
			delete_option( self::PURGE_SCHEDULER_OPTION );
			++$removed;
		}

		if ( $missing !== get_option( self::TENANT_INDEX_OPTION, $missing ) ) {
			delete_option( self::TENANT_INDEX_OPTION );
			++$removed;
		}

		return $removed;
	}

	public function effective_period_seconds( string $scheduler_mode ): int {
		return self::SCHEDULER_ACTION_SCHEDULER === $scheduler_mode
			? self::ACTION_SCHEDULER_PERIOD_SECONDS
			: self::WP_CRON_PERIOD_SECONDS;
	}

	/** @return array<string,mixed> */
	private function load_state( string $tenant_id ): array {
		$value = get_option( $this->state_option_name( $tenant_id ), array() );
		return is_array( $value ) ? $value : array();
	}

	/**
	 * @param array<string,mixed> $changes
	 */
	private function write_state( string $tenant_id, array $changes ): void {
		$tenant_id = $this->normalize_tenant_id( $tenant_id );
		if ( '' === $tenant_id ) {
			return;
		}

		$state = $this->load_state( $tenant_id );
		$mode = $this->resolve_scheduler_mode( $state['scheduler_mode'] ?? null, $changes['scheduler_mode'] ?? null );
		$defaults = array(
			'last_attempt_at' => null,
			'last_success_at' => null,
			'last_outcome' => null,
			'last_purged_count' => null,
			'backlog_remaining' => null,
			'backlog_oldest_age_seconds' => null,
			'batch_cap_reached' => false,
			'scheduler_mode' => $mode,
			'effective_period_seconds' => $this->effective_period_seconds( $mode ),
		);
		$state = array_merge( $defaults, $state, $changes );
		$state['scheduler_mode'] = $mode;
		$state['effective_period_seconds'] = $this->effective_period_seconds( $mode );

		if ( array_key_exists( $tenant_id, $this->active_leases ) ) {
			$owner = $this->active_leases[ $tenant_id ];
			$fencing_token = is_string( $owner )
				? ( $this->lease_tokens[ $tenant_id ][ $owner ] ?? null )
				: null;
			$lease_value = is_string( $owner )
				? ( $this->lease_values[ $tenant_id ][ $owner ] ?? null )
				: null;
			if ( ! is_string( $owner ) || ! is_int( $fencing_token ) || ! is_string( $lease_value ) ) {
				return;
			}

			if ( array_key_exists( 'fencing_token', $state ) && is_numeric( $state['fencing_token'] ) && (int) $state['fencing_token'] > $fencing_token ) {
				return;
			}

			$state['fencing_token'] = $fencing_token;
			$result = $this->write_fenced_state( $tenant_id, $state, $lease_value );
			if ( self::WRITE_STATUS_FENCE_REJECTED === $result['status'] && function_exists( 'do_action' ) ) {
				do_action(
					'acx_sovereign_warning',
					'reclaimer_liveness_write_fence_rejected',
					array(
						'tenant_id' => $tenant_id,
						'status' => $result['status'],
						'method' => __METHOD__,
					)
				);
			}
			return;
		}

		// Legacy callers that only report an out-of-band failure may not own a
		// lease. They may write only while no other live owner is present.
		if ( $this->has_live_lease( $tenant_id ) ) {
			return;
		}

		update_option( $this->state_option_name( $tenant_id ), $state, false );
		$this->register_tenant_key( $this->safe_tenant_key( $tenant_id ) );
	}

	/**
	 * Persist state with a compare-and-swap against the previous option value.
	 * The fencing token in that value makes a completed write from an expired
	 * owner fail after a newer owner has committed its state.
	 *
	 * @param array<string,mixed> $state
	 * @return array{committed:bool,status:string}
	 */
	private function write_fenced_state( string $tenant_id, array $state, string $lease_value ): array {
		global $wpdb;
		if (
			! isset( $wpdb )
			|| ! is_object( $wpdb )
			|| ! isset( $wpdb->options )
			|| ! is_string( $wpdb->options )
			|| ! method_exists( $wpdb, 'prepare' )
			|| ! method_exists( $wpdb, 'query' )
		) {
			return array(
				'committed' => false,
				'status' => self::WRITE_STATUS_NO_OP,
			);
		}

		$fence_available = false;
		if ( ! $this->lease_is_current( $wpdb, $tenant_id, $lease_value, $fence_available ) ) {
			return array(
				'committed' => false,
				'status' => self::WRITE_STATUS_FENCE_REJECTED,
			);
		}

		$option_name = $this->state_option_name( $tenant_id );
		$this->register_tenant_key( $this->safe_tenant_key( $tenant_id ) );
		$previous = $this->load_state( $tenant_id );
		if ( array() === $previous ) {
			$inserted = add_option( $option_name, $state, '', false );
			if ( $inserted ) {
				return array(
					'committed' => true,
					'status' => $fence_available
						? self::WRITE_STATUS_COMMITTED
						: self::WRITE_STATUS_COMMITTED_WITHOUT_FENCE,
				);
			}

			// Another owner may have inserted the first row after the read above.
			// Re-read once, then use the normal bounded CAS path against its value.
			$previous = $this->load_state( $tenant_id );
		}

		$query = $wpdb->prepare(
			'UPDATE %i AS state INNER JOIN %i AS lease ON lease.option_name = %s AND BINARY lease.option_value = %s SET state.option_value = %s WHERE state.option_name = %s AND BINARY state.option_value = %s',
			$wpdb->options,
			$wpdb->options,
			$this->lease_option_name( $tenant_id ),
			$lease_value,
			serialize( $state ),
			$option_name,
			serialize( $previous )
		);
		$result = $wpdb->query( $query );
		$affected = is_numeric( $result ) ? (int) $result : (int) ( $wpdb->rows_affected ?? 0 );
		if ( $affected > 0 ) {
			return array(
				'committed' => true,
				'status' => $fence_available
					? self::WRITE_STATUS_COMMITTED
					: self::WRITE_STATUS_COMMITTED_WITHOUT_FENCE,
			);
		}

		// Re-check before the adapter-compatible CAS fallback. Production MySQL
		// uses the joined UPDATE above; the second form is for lightweight
		// adapters that cannot model a self-join on wp_options.
		$retry_fence_available = false;
		if ( ! $this->lease_is_current( $wpdb, $tenant_id, $lease_value, $retry_fence_available ) ) {
			return array(
				'committed' => false,
				'status' => self::WRITE_STATUS_FENCE_REJECTED,
			);
		}
		$fence_available = $fence_available && $retry_fence_available;

		$query = $wpdb->prepare(
			'UPDATE ' . $wpdb->options . ' SET option_value = %s WHERE option_name = %s AND BINARY option_value = %s',
			serialize( $state ),
			$option_name,
			serialize( $previous )
		);
		$result = $wpdb->query( $query );
		$affected = is_numeric( $result ) ? (int) $result : (int) ( $wpdb->rows_affected ?? 0 );
		if ( $affected <= 0 ) {
			return array(
				'committed' => false,
				'status' => self::WRITE_STATUS_NO_OP,
			);
		}

		return array(
			'committed' => true,
			'status' => $fence_available
				? self::WRITE_STATUS_COMMITTED
				: self::WRITE_STATUS_COMMITTED_WITHOUT_FENCE,
		);
	}

	private function lease_is_current(
		object $wpdb,
		string $tenant_id,
		string $lease_value,
		?bool &$fence_available = null
	): bool {
		$stored_lease_value = $this->read_lease_value( $wpdb, $this->lease_option_name( $tenant_id ) );
		$fence_available = null !== $stored_lease_value;
		if ( null === $stored_lease_value ) {
			// Some test and migration adapters cannot read raw option rows. The
			// conditional state CAS still fences already-committed newer writers.
			return true;
		}

		return $stored_lease_value === $lease_value;
	}

	private function has_live_lease( string $tenant_id ): bool {
		global $wpdb;
		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! isset( $wpdb->options ) || ! is_string( $wpdb->options ) ) {
			return false;
		}

		$lease_value = $this->read_lease_value( $wpdb, $this->lease_option_name( $tenant_id ) );
		$parsed_lease = is_string( $lease_value ) ? $this->parse_lease_value( $lease_value ) : null;
		return is_array( $parsed_lease ) && $parsed_lease['expires_at'] > $this->now();
	}

	private function read_lease_value( object $wpdb, string $option_name ): ?string {
		if ( ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$query = $wpdb->prepare(
			'SELECT option_value FROM %i WHERE option_name = %s',
			$wpdb->options,
			$option_name
		);
		$value = $wpdb->get_var( $query );
		return is_string( $value ) ? $value : null;
	}

	/** @return array{owner:string,fencing_token:int,expires_at:int}|null */
	private function parse_lease_value( string $lease_value ): ?array {
		$parts = explode( '|', $lease_value );
		if ( 3 !== count( $parts ) || '' === $parts[0] || ! is_numeric( $parts[1] ) || ! is_numeric( $parts[2] ) ) {
			return null;
		}

		$fencing_token = (int) $parts[1];
		$expires_at = (int) $parts[2];
		if ( $fencing_token < 1 || $expires_at < 0 ) {
			return null;
		}

		return array(
			'owner' => $parts[0],
			'fencing_token' => $fencing_token,
			'expires_at' => $expires_at,
		);
	}

	private function resolve_scheduler_mode( $stored_mode, ?string $requested_mode ): string {
		if ( self::SCHEDULER_ACTION_SCHEDULER === $requested_mode || self::SCHEDULER_WP_CRON === $requested_mode ) {
			return $requested_mode;
		}
		if ( self::SCHEDULER_ACTION_SCHEDULER === $stored_mode || self::SCHEDULER_WP_CRON === $stored_mode ) {
			return $stored_mode;
		}

		return $this->current_scheduler_mode();
	}

	private function normalize_tenant_id( string $tenant_id ): string {
		return trim( $tenant_id );
	}

	private function state_option_name( string $tenant_id ): string {
		return self::OPTION_PREFIX . $this->safe_tenant_key( $tenant_id );
	}

	private function lease_option_name( string $tenant_id ): string {
		return self::LEASE_OPTION_PREFIX . $this->safe_tenant_key( $tenant_id );
	}

	private function register_tenant_key( string $safe_key ): void {
		if ( '' === $safe_key ) {
			return;
		}

		$registered_keys = get_option( self::TENANT_INDEX_OPTION, array() );
		$tenant_keys = array();
		if ( is_array( $registered_keys ) ) {
			foreach ( $registered_keys as $registered_key ) {
				if ( is_string( $registered_key ) && '' !== $registered_key && ! in_array( $registered_key, $tenant_keys, true ) ) {
					$tenant_keys[] = $registered_key;
				}
			}
		}

		if ( in_array( $safe_key, $tenant_keys, true ) ) {
			return;
		}

		$tenant_keys[] = $safe_key;
		sort( $tenant_keys, SORT_STRING );
		update_option( self::TENANT_INDEX_OPTION, $tenant_keys, false );
	}

	private function safe_tenant_key( string $tenant_id ): string {
		$safe = preg_replace( '/[^A-Za-z0-9_\\-:]/', '_', $tenant_id );
		return is_string( $safe ) && '' !== $safe ? $safe : hash( 'sha256', $tenant_id );
	}

	private function now(): int {
		$value = is_callable( $this->clock ) ? ( $this->clock )() : time();
		if ( $value instanceof DateTimeInterface ) {
			return $value->getTimestamp();
		}
		if ( is_numeric( $value ) ) {
			return (int) $value;
		}
		if ( is_string( $value ) ) {
			$timestamp = strtotime( $value );
			if ( false !== $timestamp ) {
				return $timestamp;
			}
		}

		return time();
	}

	private function now_iso8601(): string {
		return gmdate( 'Y-m-d\\TH:i:s\\Z', $this->now() );
	}

	private function normalize_timestamp( $value ): ?string {
		if ( ! is_string( $value ) || '' === trim( $value ) ) {
			return null;
		}

		$timestamp = strtotime( $value );
		return false === $timestamp ? null : gmdate( 'Y-m-d\\TH:i:s\\Z', $timestamp );
	}

	private function timestamp_to_epoch( string $timestamp ): int {
		$value = strtotime( $timestamp );
		return false === $value ? $this->now() : (int) $value;
	}

	private function normalize_outcome( $value ): ?string {
		return in_array( $value, array( self::OUTCOME_SUCCESS, self::OUTCOME_FAILED, self::OUTCOME_LOCK_CONTENDED ), true )
			? (string) $value
			: null;
	}

	private function nullable_non_negative_int( $value ): ?int {
		if ( null === $value || ! is_numeric( $value ) ) {
			return null;
		}

		return max( 0, (int) $value );
	}
}
