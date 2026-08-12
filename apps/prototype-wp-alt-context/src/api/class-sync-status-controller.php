<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/../sovereign/repositories/interface-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/interface-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-drain.php';
require_once __DIR__ . '/../sovereign/sync/interface-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-client.php';
require_once __DIR__ . '/../sovereign/sync/class-snapshot-projector.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-result.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';

use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\SyncPullResult;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJob;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use Throwable;
use WP_REST_Request;
use WP_REST_Response;

use function do_action;
use function is_string;
use function max;
use function method_exists;
use function sprintf;
use function trim;

class SyncStatusController extends AbstractRecognitionProxyController {
	private const RESET_TABLE_SUFFIXES = array(
		'acx_clusters',
		'acx_identity_members',
		'acx_sync_outbox',
	);

	private SyncStateRepositoryInterface $sync_state_repository;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?SyncPullJobFactory $sync_pull_job_factory;
	private OutboxDrain $outbox_drain;
	private ?string $sync_pull_job_error;
	private bool $sync_pull_job_resolution_failed;

	public function __construct(
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null,
		?OutboxDrain $outbox_drain = null
	) {
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->sync_pull_job = $sync_pull_job;
		$this->sync_pull_job_factory = $sync_pull_job_factory;
		$this->outbox_drain = $outbox_drain ?? new OutboxDrain();
		$this->sync_pull_job_error = null;
		$this->sync_pull_job_resolution_failed = false;
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/sync-status',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_sync_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/sync/trigger',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'trigger_sync' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/sync/reset-mirror',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'reset_mirror' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/sync/retry-failed',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'bulk_retry_failed_operations' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);
	}

	public function get_sync_status( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$version   = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$updated   = $this->sync_state_repository->get_last_updated( $tenant_id );
		$curation_state = $this->get_curation_sync_state( $tenant_id );
		$last_sync_result = $this->sync_state_repository->get_last_sync_result( $tenant_id );

		return new WP_REST_Response(
			$this->build_sync_status_payload( $version, $updated, $curation_state, $last_sync_result ),
			200
		);
	}

	public function trigger_sync( WP_REST_Request $request ): WP_REST_Response {
		return $this->run_sync_action( false );
	}

	/**
	 * Requeue every failed outbox push for the tenant in one action (E15-35 Slice 2).
	 *
	 * The maintenance service (via the OutboxDrain delegator) paces the requeued rows
	 * across drain cycles and schedules the next drain, so recovery starts promptly
	 * without re-creating the incident's thundering herd.
	 */
	public function bulk_retry_failed_operations( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$requeued = $this->outbox_drain->retry_failed_operations_bulk( $tenant_id );
		if ( false === $requeued ) {
			return new WP_REST_Response(
				array(
					'code'    => 'acx_bulk_retry_failed',
					'message' => 'Could not requeue failed sync operations.',
				),
				500
			);
		}

		return new WP_REST_Response(
			array(
				'requeued'         => $requeued,
				'failed_remaining' => $this->outbox_drain->count_failed_operations( $tenant_id ),
			),
			200
		);
	}

	public function reset_mirror( WP_REST_Request $request ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();

		try {
			$this->reset_projection_tables_transactionally( $tenant_id );
		} catch ( Throwable $e ) {
			return new WP_REST_Response(
				array(
					'code'    => 'acx_reset_mirror_failed',
					'message' => 'Could not reset the local mirror.',
				),
				500
			);
		}

		do_action( 'acx_sync_mirror_reset', $tenant_id, self::RESET_TABLE_SUFFIXES );

		return $this->run_sync_action( true );
	}

	private function run_sync_action( bool $did_reset_mirror ): WP_REST_Response {
		$tenant_id = $this->get_tenant_id();
		$sync_pull_job = $this->resolve_sync_pull_job();
		$version = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$updated = $this->sync_state_repository->get_last_updated( $tenant_id );
		$curation_state = $this->get_curation_sync_state( $tenant_id );

		if ( null === $sync_pull_job ) {
			$payload = $this->build_sync_status_payload(
				$version,
				$updated,
				$curation_state,
				$this->sync_state_repository->get_last_sync_result( $tenant_id )
			);
			$payload['synced'] = false;
			$payload['reason'] = 'sync_unavailable';
			$payload['error'] = $this->sync_pull_job_error;
			if ( $did_reset_mirror ) {
				$payload['reset'] = true;
			}

			return new WP_REST_Response( $payload, 200 );
		}

		try {
			$result = $sync_pull_job->perform_bypass_cooldown( $tenant_id );
		} catch ( Throwable $e ) {
			$result = SyncPullResult::failed();
		}

		$version = $this->sync_state_repository->get_snapshot_version( $tenant_id );
		$updated = $this->sync_state_repository->get_last_updated( $tenant_id );
		$curation_state = $this->get_curation_sync_state( $tenant_id );
		$last_sync_result = $this->sync_state_repository->get_last_sync_result( $tenant_id );
		$payload = $this->build_sync_status_payload( $version, $updated, $curation_state, $last_sync_result );
		$payload['synced'] = $result->is_success();
		$payload['reason'] = $this->determine_sync_reason( $result, $version );
		if ( $did_reset_mirror ) {
			$payload['reset'] = true;
		}

		return new WP_REST_Response( $payload, 200 );
	}

	private function reset_projection_tables_transactionally( string $tenant_id ): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) || ! method_exists( $wpdb, 'prepare' ) || ! is_string( $wpdb->prefix ) ) {
			throw new \RuntimeException( 'Reset mirror requires wpdb transaction support.' );
		}

		$started = false !== $wpdb->query( 'START TRANSACTION' );
		if ( ! $started ) {
			throw new \RuntimeException( 'Could not start reset mirror transaction.' );
		}

		try {
			foreach ( self::RESET_TABLE_SUFFIXES as $suffix ) {
				$table_name = $wpdb->prefix . $suffix;
				$query      = $wpdb->prepare( 'DELETE FROM %i', $table_name );
				// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
				if ( false === $wpdb->query( $query ) ) {
					throw new \RuntimeException( sprintf( 'Could not clear reset mirror table %s.', $table_name ) );
				}
			}

			$this->sync_state_repository->reset_projection_state( $tenant_id );

			if ( false === $wpdb->query( 'COMMIT' ) ) {
				throw new \RuntimeException( 'Could not commit reset mirror transaction.' );
			}
		} catch ( Throwable $e ) {
			$wpdb->query( 'ROLLBACK' );
			throw $e;
		}
	}

	private function determine_sync_reason( SyncPullResult $result, ?int $version ): string {
		if ( ! $result->is_success() ) {
			return 'sync_failed';
		}
		if ( 0 === $version || null === $version ) {
			return 'no_remote_data';
		}
		return 'ok';
	}

	/**
	 * @return array{
	 *   pending_curation_operations:int,
	 *   failed_curation_operations:int,
	 *   conflict_count:int,
	 *   last_curation_acknowledged_at:?string,
	 *   last_curation_conflict_at:?string,
	 *   last_curation_failed_at:?string,
	 *   topology_commands:array{
	 *     pending:int,
	 *     applied:int,
	 *     failed:int,
	 *     conflict:int,
	 *     last_reconciled_at:?string
	 *   }
	 * }
	 */
	private function get_curation_sync_state( string $tenant_id ): array {
		$pending_operations = $this->sync_state_repository->get_pending_curation_operations( $tenant_id );
		$failed_operations = $this->sync_state_repository->get_failed_curation_operations( $tenant_id );
		$conflict_count = $this->sync_state_repository->get_conflict_count( $tenant_id );

		$last_acknowledged_at = null;
		$value = $this->sync_state_repository->get_last_curation_acknowledged_at( $tenant_id );
		if ( is_string( $value ) && '' !== trim( $value ) ) {
			$last_acknowledged_at = $value;
		}

		$last_conflict_at = null;
		$value = $this->sync_state_repository->get_last_curation_conflict_at( $tenant_id );
		if ( is_string( $value ) && '' !== trim( $value ) ) {
			$last_conflict_at = $value;
		}

		$last_failed_at = null;
		$value = $this->sync_state_repository->get_last_curation_failed_at( $tenant_id );
		if ( is_string( $value ) && '' !== trim( $value ) ) {
			$last_failed_at = $value;
		}

		$last_topology_reconciled_at = null;
		$value = $this->sync_state_repository->get_last_topology_reconciled_at( $tenant_id );
		if ( is_string( $value ) && '' !== trim( $value ) ) {
			$last_topology_reconciled_at = $value;
		}

		return array(
			'pending_curation_operations' => $pending_operations,
			'failed_curation_operations' => $failed_operations,
			'conflict_count' => $conflict_count,
			'last_curation_acknowledged_at' => $last_acknowledged_at,
			'last_curation_conflict_at' => $last_conflict_at,
			'last_curation_failed_at' => $last_failed_at,
			'topology_commands' => array(
				'pending' => max( 0, (int) $this->sync_state_repository->get_pending_topology_commands( $tenant_id ) ),
				'applied' => max( 0, (int) $this->sync_state_repository->get_applied_topology_commands( $tenant_id ) ),
				'failed' => max( 0, (int) $this->sync_state_repository->get_failed_topology_commands( $tenant_id ) ),
				'conflict' => max( 0, (int) $this->sync_state_repository->get_conflicted_topology_commands( $tenant_id ) ),
				'last_reconciled_at' => $last_topology_reconciled_at,
			),
		);
	}

	/**
	 * @param array{
	 *   pending_curation_operations:int,
	 *   failed_curation_operations:int,
	 *   conflict_count:int,
	 *   last_curation_acknowledged_at:?string,
	 *   last_curation_conflict_at:?string,
	 *   last_curation_failed_at:?string,
	 *   topology_commands:array{
	 *     pending:int,
	 *     applied:int,
	 *     failed:int,
	 *     conflict:int,
	 *     last_reconciled_at:?string
	 *   }
	 * } $curation_state
	 * @return array<string,mixed>
	 */
	private function build_sync_status_payload( int $version, ?string $updated, array $curation_state, string $last_sync_result ): array {
		$is_stale = $this->is_projection_stale( $updated );
		$sync_mode = $version > 0 ? 'delta' : 'full';

		return array(
			'last_snapshot_version' => $version,
			'last_synced_at' => $updated,
			'is_stale' => $is_stale,
			'sync_mode' => $sync_mode,
			'sync_health' => $this->classify_sync_health( $curation_state, $is_stale, $last_sync_result ),
			'last_sync_result' => $last_sync_result,
			'pending_curation_operations' => $curation_state['pending_curation_operations'],
			'failed_curation_operations' => $curation_state['failed_curation_operations'],
			'conflict_count' => $curation_state['conflict_count'],
			'last_curation_acknowledged_at' => $curation_state['last_curation_acknowledged_at'],
			'last_curation_conflict_at' => $curation_state['last_curation_conflict_at'],
			'last_curation_failed_at' => $curation_state['last_curation_failed_at'],
			'topology_commands' => $curation_state['topology_commands'],
		);
	}

	/**
	 * @param array{
	 *   pending_curation_operations:int,
	 *   failed_curation_operations:int,
	 *   conflict_count:int,
	 *   last_curation_acknowledged_at:?string,
	 *   last_curation_conflict_at:?string,
	 *   last_curation_failed_at:?string,
	 *   topology_commands:array{
	 *     pending:int,
	 *     applied:int,
	 *     failed:int,
	 *     conflict:int,
	 *     last_reconciled_at:?string
	 *   }
	 * } $curation_state
	 */
	private function classify_sync_health( array $curation_state, bool $is_stale, string $last_sync_result ): string {
		if ( SyncPullResult::UNREACHABLE === $last_sync_result ) {
			return 'offline';
		}

		if ( SyncPullResult::FAILED === $last_sync_result ) {
			return 'stale';
		}

		if ( ( $curation_state['failed_curation_operations'] ?? 0 ) > 0
			|| ( $curation_state['topology_commands']['failed'] ?? 0 ) > 0 ) {
			return 'failures';
		}

		if ( ( $curation_state['conflict_count'] ?? 0 ) > 0
			|| ( $curation_state['topology_commands']['conflict'] ?? 0 ) > 0 ) {
			return 'conflicts';
		}

		if ( $is_stale ) {
			return 'stale';
		}

		if ( ( $curation_state['pending_curation_operations'] ?? 0 ) > 0
			|| ( $curation_state['topology_commands']['pending'] ?? 0 ) > 0 ) {
			return 'queued';
		}

		return 'healthy';
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}
		if ( $this->sync_pull_job_resolution_failed ) {
			return null;
		}

		try {
			$this->sync_pull_job = $this->build_sync_pull_job();
		} catch ( Throwable $e ) {
			$this->sync_pull_job_error = $e->getMessage();
			$this->sync_pull_job_resolution_failed = true;
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message' => $e->getMessage(),
					'controller' => __CLASS__,
					'context' => 'sync_status_lazy_sync_pull_job',
				)
			);
			return null;
		}

		return $this->sync_pull_job;
	}

	protected function build_sync_pull_job(): SyncPullJobInterface {
		$factory = $this->sync_pull_job_factory ?? new SyncPullJobFactory(
				new ClustersRepository(),
				new IdentityMembersRepository(),
				$this->sync_state_repository
		);

		return $factory->create();
	}
}
