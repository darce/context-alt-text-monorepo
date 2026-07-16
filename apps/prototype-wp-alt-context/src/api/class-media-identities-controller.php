<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-recognition-data-source.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';

use AltContext\Sovereign\Mappers\MemberResponseMapper;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Repositories\SyncStateRepositoryInterface;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use Throwable;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_keys;
use function count;
use function do_action;
use function is_array;
use function range;
use function rest_sanitize_boolean;
use function time;
use function wp_next_scheduled;
use function wp_schedule_single_event;

class MediaIdentitiesController extends AbstractRecognitionProxyController {
	private const DATA_SOURCE_LOCAL_PROJECTION = RecognitionDataSource::LOCAL_PROJECTION;
	private const DATA_SOURCE_BACKEND_PROXY = RecognitionDataSource::BACKEND_PROXY;
	private const DATA_SOURCE_UNAVAILABLE = RecognitionDataSource::UNAVAILABLE;
	private const REQUEST_CLASS_POST_SCAN_READ = 'post_scan_read';
	private IdentityMembersRepositoryInterface $members_repository;
	private SyncStateRepositoryInterface $sync_state_repository;
	private MemberResponseMapper $member_mapper;
	private ?SyncPullJobInterface $sync_pull_job;
	private ?SyncPullJobFactory $sync_pull_job_factory;

	public function __construct(
		?IdentityMembersRepositoryInterface $members_repository = null,
		?SyncStateRepositoryInterface $sync_state_repository = null,
		?MemberResponseMapper $member_mapper = null,
		?SyncPullJobInterface $sync_pull_job = null,
		?SyncPullJobFactory $sync_pull_job_factory = null
	) {
		$this->members_repository = $members_repository ?? new IdentityMembersRepository();
		$this->sync_state_repository = $sync_state_repository ?? new SyncStateRepository();
		$this->member_mapper = $member_mapper ?? new MemberResponseMapper();
		$this->sync_pull_job = $sync_pull_job;
		$this->sync_pull_job_factory = $sync_pull_job_factory;
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/media-identities',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_media_identities' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids'     => array(
						'type'        => 'array',
						'required'    => true,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Attachment IDs to fetch detected identities for (max 100).',
					),
					'include_debug' => array(
						'type'        => 'string',
						'required'    => false,
						'description' => 'Include debug metrics in response.',
					),
				),
			)
		);
	}

	public function get_media_identities( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$tenant_id = $this->get_tenant_id();
		$media_ids = $request->get_param( 'media_ids' );
		if ( ! is_array( $media_ids ) || empty( $media_ids ) ) {
			return new WP_Error( 'missing_media_ids', 'Provide one or more media_ids to fetch identities.', array( 'status' => 400 ) );
		}

		$ids = array();
		foreach ( $media_ids as $media_id ) {
			$abs = absint( $media_id );
			if ( $abs > 0 ) {
				$ids[] = $abs;
			}
		}

		if ( empty( $ids ) || count( $ids ) > 100 ) {
			return new WP_Error( 'invalid_media_ids', 'Provide between 1 and 100 valid attachment IDs.', array( 'status' => 400 ) );
		}

		if ( $this->should_use_local_projection( $tenant_id ) ) {
			$rows = $this->members_repository->list_for_media_ids( $tenant_id, $ids );
			$payload = array(
				'identities_by_media' => $this->member_mapper->map_media_identities( $rows ),
				'data_source' => self::DATA_SOURCE_LOCAL_PROJECTION,
			);
			// Async heal only: the sovereign read must return immediately even offline.
			$this->maybe_schedule_stale_projection_heal( $tenant_id );
			return new WP_REST_Response( $payload, 200 );
		}

		$query = array(
			'tenant_id' => $tenant_id,
			'media_ids' => $ids,
		);

		$include_debug = $request->get_param( 'include_debug' );
		if ( null !== $include_debug && true === rest_sanitize_boolean( $include_debug ) ) {
			$query['include_debug'] = 'true';
		}

		$response = $this->proxy_request( 'GET', '/recognition/media/identities', array(), $query, self::REQUEST_CLASS_POST_SCAN_READ );
		if ( $this->is_backend_overloaded( $response ) ) {
			return parent::backend_overloaded_response( $response );
		}
		if ( $this->is_proxy_unavailable( $response ) ) {
			return new WP_REST_Response(
				array(
					'identities_by_media' => array(),
					'data_source' => self::DATA_SOURCE_UNAVAILABLE,
				),
				200
			);
		}

		if ( $response instanceof WP_REST_Response && 200 === $response->get_status() ) {
			return $this->maybe_bootstrap_after_proxy_read( $tenant_id, $this->normalize_backend_media_identities_response( $response ) );
		}

		return $response;
	}

	private function normalize_backend_media_identities_response( WP_REST_Response $response ): WP_REST_Response|WP_Error {
		$data = $response->get_data();

		if ( ! is_array( $data ) ) {
			return new WP_Error(
				'invalid_media_identities_payload',
				'Media identities payload must be a JSON array or identities_by_media envelope.',
				array( 'status' => 502 )
			);
		}

		if ( isset( $data['identities_by_media'] ) ) {
			if ( ! is_array( $data['identities_by_media'] ) ) {
				return new WP_Error(
					'invalid_media_identities_payload',
					'Media identities envelope must include an identities_by_media object.',
					array( 'status' => 502 )
				);
			}

			return new WP_REST_Response(
				array(
					'identities_by_media' => $data['identities_by_media'],
					'data_source'        => self::DATA_SOURCE_BACKEND_PROXY,
				),
				200
			);
		}

		if ( ! $this->is_list_payload( $data ) ) {
			return new WP_Error(
				'invalid_media_identities_payload',
				'Media identities payload must be a JSON array or identities_by_media envelope.',
				array( 'status' => 502 )
			);
		}

		$grouped = array();
		foreach ( $data as $identity ) {
			if ( ! is_array( $identity ) ) {
				return new WP_Error(
					'invalid_media_identities_payload',
					'Media identities list items must be objects with a media_id.',
					array( 'status' => 502 )
				);
			}

			$media_id = absint( $identity['media_id'] ?? 0 );
			if ( $media_id <= 0 ) {
				return new WP_Error(
					'invalid_media_identities_payload',
					'Media identities list items must include a valid media_id.',
					array( 'status' => 502 )
				);
			}

			$media_key = (string) $media_id;
			if ( ! isset( $grouped[ $media_key ] ) ) {
				$grouped[ $media_key ] = array();
			}
			$grouped[ $media_key ][] = $identity;
		}

		return new WP_REST_Response(
			array(
				'identities_by_media' => $grouped,
				'data_source'        => self::DATA_SOURCE_BACKEND_PROXY,
			),
			200
		);
	}

	/**
	 * Rows-first source selection ([DATA-14]): the projection rows are the
	 * ground truth, so a derived sync-state freshness marker must not veto
	 * the source of record. Staleness is healed asynchronously instead.
	 */
	private function should_use_local_projection( string $tenant_id ): bool {
		return $this->members_repository->has_projection_rows_for_tenant( $tenant_id );
	}

	/**
	 * After a successful proxy read, converge the projection via an inline
	 * pull, falling back to one deduped cron event when the inline pull does
	 * not succeed. Unlike ClusterProjectionSyncService::maybe_bootstrap_after_proxy_read
	 * the inline leg is cooldown-gated (`perform()`, not the bypass): this runs on
	 * the visitor read path, so SyncPullJob's failure cooldowns bound repeated
	 * pull cost during partial outages and dedup concurrent requests; a
	 * cooldown-skipped pull still schedules the cron fallback, which performs
	 * the bypass pull. A throwing pull must never break the proxy response.
	 */
	private function maybe_bootstrap_after_proxy_read( string $tenant_id, WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		if ( $response->get_status() < 200 || $response->get_status() >= 300 ) {
			return $response;
		}

		$sync_pull_job = $this->resolve_sync_pull_job();
		if ( null === $sync_pull_job ) {
			return $response;
		}

		try {
			$inline_result = $sync_pull_job->perform( $tenant_id );
		} catch ( Throwable $throwable ) {
			do_action(
				'acx_sync_pull_failed',
				array(
					'tenant_id' => $tenant_id,
					'context' => 'bootstrap_after_proxy_read',
					'message' => $throwable->getMessage(),
				)
			);
			$this->schedule_bootstrap_sync_event( $tenant_id );
			return $response;
		}

		if ( ! $inline_result->is_success() ) {
			$this->schedule_bootstrap_sync_event( $tenant_id );
		}

		return $response;
	}

	private function maybe_schedule_stale_projection_heal( string $tenant_id ): void {
		$updated_at = $this->sync_state_repository->get_last_updated( $tenant_id );
		if ( ! $this->is_projection_stale( $updated_at ) ) {
			return;
		}

		$this->schedule_bootstrap_sync_event( $tenant_id );
	}

	private function schedule_bootstrap_sync_event( string $tenant_id ): void {
		$args = array( $tenant_id );
		if ( false === wp_next_scheduled( RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, $args ) ) {
			wp_schedule_single_event( time(), RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, $args );
		}
	}

	private function resolve_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->sync_pull_job ) {
			return $this->sync_pull_job;
		}

		try {
			$factory = $this->sync_pull_job_factory ?? new SyncPullJobFactory(
				new ClustersRepository(),
				$this->members_repository,
				$this->sync_state_repository,
				new SnapshotClient()
			);
			$this->sync_pull_job = $factory->create();
		} catch ( Throwable $e ) {
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message' => $e->getMessage(),
					'controller' => __CLASS__,
					'context' => 'media_identities_lazy_sync_pull_job',
				)
			);
			return null;
		}

		return $this->sync_pull_job;
	}

	private function is_list_payload( array $data ): bool {
		if ( array() === $data ) {
			return true;
		}

		return array_keys( $data ) === range( 0, count( $data ) - 1 );
	}
}
