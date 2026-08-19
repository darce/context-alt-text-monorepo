<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-media-detail-controller.php';
require_once __DIR__ . '/class-recognition-data-source.php';
require_once __DIR__ . '/class-tenant-identity.php';
require_once __DIR__ . '/services/class-person-resolution-service.php';
require_once __DIR__ . '/services/class-cluster-person-bind-service.php';
require_once __DIR__ . '/../support/trait-runs-transactional.php';
require_once __DIR__ . '/../sovereign/repositories/class-cluster-curation-writer.php';
require_once __DIR__ . '/../sovereign/repositories/class-clusters-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-roster-entry-projection-repository.php';
require_once __DIR__ . '/../sovereign/repositories/class-sync-state-repository.php';
require_once __DIR__ . '/../sovereign/sync/interface-sync-pull-job.php';
require_once __DIR__ . '/../sovereign/sync/interface-targeted-sync-pull-job.php';
require_once __DIR__ . '/../support/class-telemetry.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-drain.php';
require_once __DIR__ . '/../sovereign/sync/class-outbox-writer.php';
require_once __DIR__ . '/../sovereign/sync/class-split-topology-command-drain.php';
require_once __DIR__ . '/../sovereign/sync/class-sync-pull-job-factory.php';

use AltContext\Api\RecognitionController;
use AltContext\Api\Services\ClusterPersonBindService;
use AltContext\Api\Services\PersonResolutionService;
use AltContext\Support\RunsTransactional;
use AltContext\Sovereign\Repositories\ClusterCurationWriter;
use AltContext\Sovereign\Repositories\ClustersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\RosterEntryProjectionRepository;
use AltContext\Sovereign\Repositories\SyncStateRepository;
use AltContext\Sovereign\Sync\OutboxDrain;
use AltContext\Sovereign\Sync\OutboxWriter;
use AltContext\Sovereign\Sync\SnapshotClient;
use AltContext\Sovereign\Sync\SplitTopologyCommandDrain;
use AltContext\Sovereign\Sync\SyncPullJobFactory;
use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\TargetedSyncPullJobInterface;
use AltContext\Support\Telemetry;
use Throwable;
use WP_Error;
use WP_Query;
use WP_REST_Request;
use WP_REST_Response;
use function absint;
use function add_action;
use function current_time;
use function do_action;
use function trim;
use function current_user_can;
use function get_edit_post_link;
use function get_option;
use function get_post_meta;
use function get_post_mime_type;
use function get_post_modified_time;
use function get_site_url;
use function get_the_title;
use function is_array;
use function is_object;
use function is_wp_error;
use function md5;
use function method_exists;
use function register_rest_route;
use function rest_ensure_response;
use function sanitize_text_field;
use function sprintf;
use function update_option;
use function wp_get_attachment_image_sizes;
use function wp_get_attachment_image_src;
use function wp_get_attachment_image_srcset;
use function wp_get_attachment_image_url;
use function wp_get_attachment_metadata;
use function wp_get_object_terms;
use function wp_generate_uuid4;

class Api {
	use RunsTransactional;

	private RecognitionController $recognitionController;
	private MediaDetailController $mediaDetailController;
	private SettingsController $settingsController;
	private ?XmpEmbedController $xmpEmbedController;
	private OutboxDrain $outboxDrain;
	private SplitTopologyCommandDrain $splitTopologyCommandDrain;
	private ?SyncPullJobInterface $bootstrapSyncPullJob;

	public function __construct( ?XmpEmbedController $xmp_embed_controller = null, ?OutboxDrain $outbox_drain = null, ?SplitTopologyCommandDrain $split_topology_command_drain = null, ?SyncPullJobInterface $bootstrap_sync_pull_job = null ) {
		$this->recognitionController = new RecognitionController();
		$this->mediaDetailController = new MediaDetailController();
		$this->settingsController = new SettingsController();
		$this->xmpEmbedController = $xmp_embed_controller;
		$this->outboxDrain = $outbox_drain ?? new OutboxDrain();
		$this->splitTopologyCommandDrain = $split_topology_command_drain ?? new SplitTopologyCommandDrain();
		$this->bootstrapSyncPullJob = $bootstrap_sync_pull_job;
	}

	public function init(): void {
		$this->outboxDrain->register();
		$this->splitTopologyCommandDrain->register();
		// E15-37: wp-cron never fires rest_api_init, so the bootstrap-sync handler
		// must be bound at plugin load or scheduled events dispatch to zero listeners.
		add_action( RecognitionDataSource::BOOTSTRAP_SYNC_HOOK, array( $this, 'handle_bootstrap_sync' ), 10, 2 );
		add_action( 'rest_api_init', array( $this, 'register_routes' ) );
	}

	/**
	 * @param list<string> $cluster_ids
	 */
	public function handle_bootstrap_sync( string $tenant_id, array $cluster_ids = array() ): void {
		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id ) {
			return;
		}

		$sync_pull_job = $this->resolve_bootstrap_sync_pull_job();
		if ( null === $sync_pull_job ) {
			return;
		}

		$normalized_ids = array();
		foreach ( $cluster_ids as $cluster_id ) {
			$id = sanitize_text_field( (string) $cluster_id );
			if ( '' !== $id ) {
				$normalized_ids[] = $id;
			}
		}
		$normalized_ids = array_values( array_unique( $normalized_ids ) );
		if ( array() !== $normalized_ids && $sync_pull_job instanceof TargetedSyncPullJobInterface ) {
			$sync_pull_job->perform_targeted_snapshot( $normalized_tenant_id, $normalized_ids );
			return;
		}
		if ( array() !== $normalized_ids ) {
			Telemetry::log_line(
				sprintf(
					'[acx] bootstrap sync received %d cluster ids but job is not targeted-capable; falling back to full-tenant sync',
					count( $normalized_ids )
				)
			);
		}

		$sync_pull_job->perform_bypass_cooldown( $normalized_tenant_id );
	}

	private function resolve_bootstrap_sync_pull_job(): ?SyncPullJobInterface {
		if ( null !== $this->bootstrapSyncPullJob ) {
			return $this->bootstrapSyncPullJob;
		}

		try {
			$factory = new SyncPullJobFactory(
				new ClustersRepository(),
				new IdentityMembersRepository(),
				new SyncStateRepository(),
				new SnapshotClient()
			);
			$this->bootstrapSyncPullJob = $factory->create();
		} catch ( Throwable $e ) {
			do_action(
				'acx_recognition_composition_failed',
				array(
					'message' => $e->getMessage(),
					'controller' => __CLASS__,
					'context' => 'bootstrap_sync_cron_handler',
				)
			);
			return null;
		}

		return $this->bootstrapSyncPullJob;
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/workbench/media',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_workbench_media' ),
				'permission_callback' => array( $this, 'can_view_media_queue' ),
				'args'                => $this->get_workbench_media_args(),
			)
		);

		register_rest_route(
			'acx/v1',
			'/workbench/media/detail',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this->mediaDetailController, 'get_media_details' ),
				'permission_callback' => array( $this, 'can_view_media_queue' ),
				'args'                => $this->get_workbench_media_detail_args(),
			)
		);

		register_rest_route(
			'acx/v1',
			'/dashboard/stats',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_dashboard_stats' ),
				'permission_callback' => array( $this, 'can_manage_roster' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/roster/persons',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'create_person' ),
				'permission_callback' => array( $this, 'can_manage_roster' ),
				'args'                => array(
					'name' => array(
						'required'          => true,
						'type'              => 'string',
						'sanitize_callback' => 'sanitize_text_field',
					),
					'tags' => array(
						'type'    => 'array',
						'default' => array(),
						'items'   => array( 'type' => 'string' ),
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/roster/persons/(?P<id>\d+)',
			array(
				array(
					'methods'             => 'PUT',
					'callback'            => array( $this, 'update_person' ),
					'permission_callback' => array( $this, 'can_manage_roster' ),
					'args'                => array(
						'name' => array(
							'type'              => 'string',
							'sanitize_callback' => 'sanitize_text_field',
						),
						'tags' => array(
							'type'  => 'array',
							'items' => array( 'type' => 'string' ),
						),
					),
				),
				array(
					'methods'             => 'DELETE',
					'callback'            => array( $this, 'delete_person' ),
					'permission_callback' => array( $this, 'can_manage_roster' ),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/roster/entries',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_roster_entries' ),
				'permission_callback' => array( $this, 'can_manage_roster' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/roster/clusters/(?P<cluster_id>[a-f0-9-]+)/commit',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'commit_roster_cluster' ),
				'permission_callback' => array( $this, 'can_manage_roster' ),
			)
		);

		$this->recognitionController->register_routes();
		$this->settingsController->register_routes();
		if ( $this->xmpEmbedController instanceof XmpEmbedController ) {
			$this->xmpEmbedController->register_routes();
		}
	}

	public function can_view_media_queue(): bool {
		return current_user_can( 'upload_files' );
	}

	public function can_manage_roster(): bool {
		return current_user_can( 'manage_options' );
	}

	/**
	 * Handle GET /workbench/media requests.
	 *
	 * Note: per_page limits are enforced via REST API schema validation (see get_workbench_media_args).
	 */
	public function get_workbench_media( WP_REST_Request $request ): WP_REST_Response {
		$page     = (int) $request->get_param( 'page' );
		$per_page = (int) $request->get_param( 'per_page' );
		$search   = (string) $request->get_param( 'search' );
		$status   = (string) $request->get_param( 'status' );

		$args = array(
			'post_type'      => 'attachment',
			'post_status'    => 'inherit',
			'post_mime_type' => 'image',
			'posts_per_page' => $per_page,
			'paged'          => $page,
			'orderby'        => 'date',
			'order'          => 'DESC',
			'fields'         => 'ids',
		);

		if ( ! empty( $search ) ) {
			$args['s'] = $search;
		}

		if ( 'missing' === $status ) {
			// Empty alt AND not decorative. Decorative exclusion mirrors
			// DescriptionCandidateService::build_row so marked images leave the
			// missing queue (and the coverage probe that reuses this filter).
			$args['meta_query'] = array(
				'relation' => 'AND',
				array(
					'relation' => 'OR',
					array(
						'key'     => '_wp_attachment_image_alt',
						'compare' => 'NOT EXISTS',
					),
					array(
						'key'     => '_wp_attachment_image_alt',
						'value'   => '',
						'compare' => '=',
					),
				),
				array(
					'relation' => 'OR',
					array(
						'key'     => 'acx_alt_decorative',
						'compare' => 'NOT EXISTS',
					),
					array(
						'key'     => 'acx_alt_decorative',
						'value'   => '1',
						'compare' => '!=',
					),
				),
			);
		}

		$query       = new WP_Query( $args );
		$attachments = $query->posts;

		$items = array_map(
			function ( int $attachment_id ): array {
				$alt_text = get_post_meta( $attachment_id, '_wp_attachment_image_alt', true );
				// Precedence matches DescriptionCandidateService::build_row:
				// non-empty alt wins over a leftover decorative marker; marker
				// '1' with empty alt is treated as done (status complete).
				$has_alt        = '' !== trim( (string) $alt_text );
				$decorative_raw = get_post_meta( $attachment_id, 'acx_alt_decorative', true );
				$is_decorative  = is_string( $decorative_raw ) && '1' === $decorative_raw;
				$thumb_medium = wp_get_attachment_image_src( $attachment_id, 'medium' );
				$thumb_url    = wp_get_attachment_image_url( $attachment_id, 'full' );
				$thumb        = is_array( $thumb_medium ) && isset( $thumb_medium[0] ) ? $thumb_medium[0] : $thumb_url;
				$thumb_width  = is_array( $thumb_medium ) && isset( $thumb_medium[1] ) ? (int) $thumb_medium[1] : null;
				$thumb_height = is_array( $thumb_medium ) && isset( $thumb_medium[2] ) ? (int) $thumb_medium[2] : null;
				$thumb_srcset = wp_get_attachment_image_srcset( $attachment_id, 'medium' );
				$thumb_sizes  = wp_get_attachment_image_sizes( $attachment_id, 'medium' );
				$terms    = wp_get_object_terms( $attachment_id, 'post_tag', array( 'fields' => 'names' ) );

				return array(
					'id'           => $attachment_id,
					'title'        => get_the_title( $attachment_id ),
					'status'       => ( $has_alt || $is_decorative ) ? 'complete' : 'missing',
					'thumbnailUrl' => false === $thumb ? null : $thumb,
					'thumbnailSrcset' => is_string( $thumb_srcset ) ? $thumb_srcset : null,
					'thumbnailSizes'  => is_string( $thumb_sizes ) ? $thumb_sizes : null,
					'thumbnailDimensions' => array(
						'width'  => $thumb_width,
						'height' => $thumb_height,
					),
					'altText'      => $has_alt ? $alt_text : null,
					'isDecorative' => $is_decorative,
					'editUrl'      => get_edit_post_link( $attachment_id, '' ),
					'tags'         => is_wp_error( $terms ) || ! is_array( $terms ) ? array() : array_values( $terms ),
				);
			},
			$attachments
		);

		$response = array(
			'items'      => $items,
			'total'      => (int) $query->found_posts,
			'totalPages' => max( 1, (int) $query->max_num_pages ),
		);

		return rest_ensure_response( $response );
	}

	/**
	 * Allowed query parameters for workbench media listing.
	 *
	 * @return array<string,array<string,mixed>>
	 */
	private function get_workbench_media_args(): array {
		return array(
			'page'     => array(
				'description'       => 'Page number (1-indexed).',
				'type'              => 'integer',
				'default'           => 1,
				'sanitize_callback' => 'absint',
				'minimum'           => 1,
			),
			'per_page' => array(
				'description'       => 'Items per page.',
				'type'              => 'integer',
				'default'           => 20,
				'sanitize_callback' => 'absint',
				'minimum'           => 1,
				'maximum'           => 100,
			),
			'search'   => array(
				'description'       => 'Optional search term applied to attachment title and meta.',
				'type'              => 'string',
				'required'          => false,
				'sanitize_callback' => 'sanitize_text_field',
			),
			'status'   => array(
				'description' => 'Filter by media status.',
				'type'        => 'string',
				'default'     => 'all',
				'enum'        => array( 'missing', 'all' ),
			),
		);
	}

	/**
	 * Allowed query parameters for deferred workbench media detail loading.
	 *
	 * @return array<string,array<string,mixed>>
	 */
	private function get_workbench_media_detail_args(): array {
		return array(
			'ids' => array(
				'description' => 'Attachment IDs to enrich after the initial shell paint.',
				'type'        => 'array',
				'required'    => false,
				'items'       => array(
					'type'    => 'integer',
					'minimum' => 1,
				),
			),
		);
	}

	public function get_roster_entries( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$projection_repository = new RosterEntryProjectionRepository();
		return rest_ensure_response( $projection_repository->list_entries( $this->get_local_tenant_id() ) );
	}

	public function commit_roster_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$person_id            = $request->get_param( 'roster_entry_id' );
		$new_name             = $request->get_param( 'new_entry_name' );
		$resolved_person_name = null;
		$person_uuid          = null;
		$table_persons  = $wpdb->prefix . 'acx_persons';
		$table_clusters = $wpdb->prefix . 'acx_clusters';

		if ( ! $this->begin_database_transaction() ) {
			return new WP_Error( 'acx_db_error', __( 'Could not start local transaction.', 'alt-context' ), array( 'status' => 500 ) );
		}

		// If new name provided, resolve-or-create person inside the caller's transaction.
		// PersonResolutionService is transaction-agnostic (no nested START TRANSACTION).
		if ( ! $person_id && $new_name ) {
			$new_name = sanitize_text_field( (string) $new_name );
			if ( ! empty( trim( $new_name ) ) ) {
				$resolver = new PersonResolutionService();
				$resolved = $resolver->resolve_or_create(
					$new_name,
					function ( string $created_person_uuid, string $created_name, array $created_tags ): bool {
						return $this->enqueue_curation_operation(
							'person_created',
							'person',
							$created_person_uuid,
							1,
							array(
								'person_uuid' => $created_person_uuid,
								'name'        => $created_name,
								'tags'        => $created_tags,
							)
						);
					}
				);
				if ( is_wp_error( $resolved ) ) {
					$this->rollback_database_transaction();
					return $resolved;
				}

				$person_id            = $resolved['person_id'];
				$person_uuid          = $resolved['person_uuid'];
				$resolved_person_name = $resolved['name'];
			}
		}

		$person_id = $person_id ? absint( $person_id ) : null;
		if ( null !== $person_id && ( ! is_string( $person_uuid ) || '' === trim( $person_uuid ) ) ) {
			$person_uuid = $this->get_person_uuid_by_id( $person_id, $table_persons );
		}

		if ( null !== $person_id && ( ! is_string( $person_uuid ) || '' === trim( $person_uuid ) ) ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not resolve person UUID for cluster assignment.', 'alt-context' ), array( 'status' => 500 ) );
		}

		if ( null !== $person_id && ( ! is_string( $resolved_person_name ) || '' === trim( $resolved_person_name ) ) ) {
			$resolved_person_name = $this->get_person_name_by_id( $person_id, $table_persons );
		}

		$now = current_time( 'mysql' );

		if ( null !== $person_id ) {
			$binder = new ClusterPersonBindService();
			$bound  = $binder->bind_cluster_to_person(
				$cluster_id,
				$person_id,
				function ( string $operation_type, string $bound_cluster_id, int $local_revision, array $payload ): bool {
					return $this->enqueue_curation_operation(
						$operation_type,
						'cluster',
						$bound_cluster_id,
						$local_revision,
						$payload
					);
				},
				is_string( $person_uuid ) ? $person_uuid : null,
				is_string( $resolved_person_name ) ? $resolved_person_name : null
			);
			if ( is_wp_error( $bound ) ) {
				$this->rollback_database_transaction();
				return $bound;
			}
			$person_uuid          = $bound['person_uuid'];
			$resolved_person_name = $bound['person_name'];
			$now                  = $bound['updated_at'];
		} else {
			$update_data = array(
				'person_id'         => $person_id,
				'curation_state'    => 'confirmed',
				'is_user_confirmed' => 1,
				'updated_at'        => $now,
			);
			$update_fmt  = array( null, '%s', '%d', '%s' );

			$cluster_updated = $wpdb->update(
				$table_clusters,
				$update_data,
				array( 'cluster_uuid' => $cluster_id ),
				$update_fmt,
				array( '%s' )
			);
			if ( false === $cluster_updated ) {
				$this->rollback_database_transaction();
				return new WP_Error( 'acx_db_error', __( 'Could not update cluster assignment.', 'alt-context' ), array( 'status' => 500 ) );
			}

			$revision_updated = $wpdb->query(
				$wpdb->prepare(
					'UPDATE %i SET local_revision = local_revision + 1 WHERE cluster_uuid = %s',
					$table_clusters,
					$cluster_id
				)
			);
			if ( false === $revision_updated ) {
				$this->rollback_database_transaction();
				return new WP_Error( 'acx_db_error', __( 'Could not update cluster revision.', 'alt-context' ), array( 'status' => 500 ) );
			}

			$local_revision = (int) $wpdb->get_var(
				$wpdb->prepare( 'SELECT local_revision FROM %i WHERE cluster_uuid = %s', $table_clusters, $cluster_id )
			);
			$queued = $this->enqueue_curation_operation(
				'cluster_person_unbound',
				'cluster',
				$cluster_id,
				max( 1, $local_revision ),
				array(
					'cluster_uuid' => $cluster_id,
					'person_uuid'  => null,
					'person_name'  => null,
				)
			);
			if ( ! $queued ) {
				$this->rollback_database_transaction();
				return new WP_Error( 'acx_db_error', __( 'Could not queue curation replay operation.', 'alt-context' ), array( 'status' => 500 ) );
			}
		}

		if ( ! $this->commit_database_transaction() ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not commit local transaction.', 'alt-context' ), array( 'status' => 500 ) );
		}

		// Bound person identity for both create and rebind outcomes (E21-9 Slice 1 DoD).
		return rest_ensure_response(
			array(
				'cluster_id'  => $cluster_id,
				'person_id'   => $person_id,
				'person_uuid' => ( null === $person_id ) ? null : ( is_string( $person_uuid ) ? $person_uuid : null ),
				'person_name' => ( null === $person_id || ! is_string( $resolved_person_name ) || '' === trim( $resolved_person_name ) ) ? null : trim( $resolved_person_name ),
				'updated_at'  => $now,
			)
		);
	}

	public function create_person( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$name = sanitize_text_field( (string) $request->get_param( 'name' ) );
		$tags = (array) $request->get_param( 'tags' );

		if ( empty( trim( $name ) ) ) {
			return new WP_Error(
				'acx_invalid_name',
				__( 'Person name cannot be empty.', 'alt-context' ),
				array( 'status' => 400 )
			);
		}

		$table_name      = $wpdb->prefix . 'acx_persons';
		$normalized_name = PersonResolutionService::normalize_name( $name );

		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! is_string( $tenant_id ) || '' === trim( $tenant_id ) ) {
			return new WP_Error( 'acx_db_error', __( 'Tenant identity is unavailable.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$existing = $wpdb->get_var(
			$wpdb->prepare(
				'SELECT id FROM %i WHERE normalized_name = %s AND tenant_id = %s',
				$table_name,
				$normalized_name,
				$tenant_id
			)
		);
		if ( $existing ) {
			return new WP_Error( 'acx_person_exists', __( 'A person with this name already exists.', 'alt-context' ), array( 'status' => 409 ) );
		}

		$person_uuid = wp_generate_uuid4();
		$now         = current_time( 'mysql' );

		if ( ! $this->begin_database_transaction() ) {
			return new WP_Error( 'acx_db_error', __( 'Could not start local transaction.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$result = $wpdb->insert(
			$table_name,
			array(
				'person_uuid'     => $person_uuid,
				'tenant_id'       => $tenant_id,
				'name'            => $name,
				'normalized_name' => $normalized_name,
				'tags'            => wp_json_encode( $tags ),
				'local_revision'  => 1,
				'created_at'      => $now,
				'updated_at'      => $now,
			),
			array( '%s', '%s', '%s', '%s', '%s', '%d', '%s', '%s' )
		);

		if ( false === $result ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not create person in database.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$person_id = $wpdb->insert_id;
		$queued = $this->enqueue_curation_operation(
			'person_created',
			'person',
			(string) $person_uuid,
			1,
			array(
				'person_uuid' => $person_uuid,
				'name'        => $name,
				'tags'        => $tags,
			)
		);

		if ( ! $queued ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not queue person creation replay operation.', 'alt-context' ), array( 'status' => 500 ) );
		}

		if ( ! $this->commit_database_transaction() ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not commit local transaction.', 'alt-context' ), array( 'status' => 500 ) );
		}

		return new WP_REST_Response(
			array(
				'id'          => $person_id,
				'person_uuid' => $person_uuid,
				'name'        => $name,
				'tags'        => $tags,
				'cluster_count' => 0,
				'created_at'  => $now,
				'updated_at'  => $now,
			),
			201
		);
	}

	public function update_person( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$id   = (int) $request->get_param( 'id' );
		$name = $request->get_param( 'name' );
		$tags = $request->get_param( 'tags' );

		if ( null !== $name && empty( trim( sanitize_text_field( (string) $name ) ) ) ) {
			return new WP_Error(
				'acx_invalid_name',
				__( 'Person name cannot be empty.', 'alt-context' ),
				array( 'status' => 400 )
			);
		}

		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! is_string( $tenant_id ) || '' === trim( $tenant_id ) ) {
			return new WP_Error( 'acx_db_error', __( 'Tenant identity is unavailable.', 'alt-context' ), array( 'status' => 500 ) );
		}

			$table_name = $wpdb->prefix . 'acx_persons';
			$person     = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d AND tenant_id = %s', $table_name, $id, $tenant_id ) );

		if ( ! $person ) {
			return new WP_Error( 'acx_person_not_found', __( 'Person not found.', 'alt-context' ), array( 'status' => 404 ) );
		}

		$update_data = array();
		$update_fmt  = array();

		if ( null !== $name ) {
			$name            = sanitize_text_field( (string) $name );
			$normalized_name = PersonResolutionService::normalize_name( $name );
			// Conflict on normalized_name policy when display name changes.
			if ( $name !== $person->name ) {
				$conflict = $wpdb->get_var(
					$wpdb->prepare(
						'SELECT id FROM %i WHERE normalized_name = %s AND id != %d AND tenant_id = %s',
						$table_name,
						$normalized_name,
						$id,
						$tenant_id
					)
				);
				if ( $conflict ) {
					return new WP_Error( 'acx_person_exists', __( 'Another person with this name already exists.', 'alt-context' ), array( 'status' => 409 ) );
				}
				$update_data['name']            = $name;
				$update_data['normalized_name'] = $normalized_name;
				$update_fmt[]                   = '%s';
				$update_fmt[]                   = '%s';
			}
		}

		if ( null !== $tags ) {
			$update_data['tags'] = wp_json_encode( (array) $tags );
			$update_fmt[]        = '%s';
		}

		if ( empty( $update_data ) ) {
			return rest_ensure_response( $person );
		}

		$now                     = current_time( 'mysql' );
		$update_data['updated_at'] = $now;
		$update_fmt[]            = '%s';

		if ( ! $this->begin_database_transaction() ) {
			return new WP_Error( 'acx_db_error', __( 'Could not start local transaction.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$result = $wpdb->update( $table_name, $update_data, array( 'id' => $id, 'tenant_id' => $tenant_id ), $update_fmt, array( '%d', '%s' ) );

		if ( false === $result ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not update person in database.', 'alt-context' ), array( 'status' => 500 ) );
		}

		if ( null !== $name && $name !== $person->name && ! $this->sync_bound_cluster_labels( $id, $name, $now, $wpdb->prefix . 'acx_clusters' ) ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not sync bound cluster labels.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$person_revision_updated = $wpdb->query(
			$wpdb->prepare(
				'UPDATE %i SET local_revision = local_revision + 1 WHERE id = %d AND tenant_id = %s',
				$table_name,
				$id,
				$tenant_id
			)
		);
		if ( false === $person_revision_updated ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not update person revision.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$local_revision = (int) $wpdb->get_var(
			$wpdb->prepare( 'SELECT local_revision FROM %i WHERE id = %d AND tenant_id = %s', $table_name, $id, $tenant_id )
		);

			$updated_person = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d AND tenant_id = %s', $table_name, $id, $tenant_id ) );
		if ( isset( $updated_person->tags ) && is_string( $updated_person->tags ) ) {
			$updated_person->tags = json_decode( $updated_person->tags, true );
		}

			$queued = $this->enqueue_curation_operation(
				'person_updated',
				'person',
				(string) ( $person->person_uuid ?? $id ),
				max( 1, $local_revision ),
				array(
					'person_uuid' => (string) ( $person->person_uuid ?? '' ),
					'name'        => (string) ( $updated_person->name ?? $person->name ),
					'tags'        => $updated_person->tags ?? array(),
				)
			);

		if ( ! $queued ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not queue person update replay operation.', 'alt-context' ), array( 'status' => 500 ) );
		}

		if ( ! $this->commit_database_transaction() ) {
			$this->rollback_database_transaction();
			return new WP_Error( 'acx_db_error', __( 'Could not commit local transaction.', 'alt-context' ), array( 'status' => 500 ) );
		}

		return rest_ensure_response( $updated_person );
	}

	public function delete_person( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$id = (int) $request->get_param( 'id' );

		$table_persons  = $wpdb->prefix . 'acx_persons';
		$table_clusters = $wpdb->prefix . 'acx_clusters';

		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! is_string( $tenant_id ) || '' === trim( $tenant_id ) ) {
			return new WP_Error( 'acx_db_error', __( 'Tenant identity is unavailable.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$person = $wpdb->get_row(
			$wpdb->prepare( 'SELECT * FROM %i WHERE id = %d AND tenant_id = %s', $table_persons, $id, $tenant_id )
		);
		if ( ! $person ) {
			return new WP_Error( 'acx_person_not_found', __( 'Person not found.', 'alt-context' ), array( 'status' => 404 ) );
		}

		return $this->run_transactional(
			function () use ( $wpdb, $id, $person, $table_persons, $table_clusters, $tenant_id ): WP_REST_Response|WP_Error {
				$affected_clusters = $wpdb->get_results(
					$wpdb->prepare(
						'SELECT cluster_uuid FROM %i WHERE person_id = %d AND tenant_id = %s',
						$table_clusters,
						$id,
						$tenant_id
					),
					ARRAY_A
				);
				if ( ! is_array( $affected_clusters ) ) {
					return new WP_Error( 'acx_db_error', __( 'Could not load clusters for person.', 'alt-context' ), array( 'status' => 500 ) );
				}

				$writer      = new ClusterCurationWriter( $table_clusters );
				$cluster_ids = array();
				foreach ( $affected_clusters as $cluster_row ) {
					$cluster_uuid = sanitize_text_field( (string) ( $cluster_row['cluster_uuid'] ?? '' ) );
					if ( '' === $cluster_uuid ) {
						continue;
					}

					if ( $writer->reset_curation( $cluster_uuid, $tenant_id ) <= 0 ) {
						return new WP_Error( 'acx_db_error', __( 'Could not dissociate person from clusters.', 'alt-context' ), array( 'status' => 500 ) );
					}

					$cluster_revision = (int) $wpdb->get_var(
						$wpdb->prepare( 'SELECT local_revision FROM %i WHERE cluster_uuid = %s', $table_clusters, $cluster_uuid )
					);

					$queued = $this->enqueue_curation_operation(
						'cluster_person_unbound',
						'cluster',
						$cluster_uuid,
						max( 1, $cluster_revision ),
						array(
							'cluster_uuid' => $cluster_uuid,
							'person_uuid'  => null,
						)
					);
					if ( ! $queued ) {
						return new WP_Error( 'acx_db_error', __( 'Could not queue cluster unbind replay operation.', 'alt-context' ), array( 'status' => 500 ) );
					}

					$label_cleared = $this->enqueue_curation_operation(
						'cluster_label_updated',
						'cluster',
						$cluster_uuid,
						max( 1, $cluster_revision ),
						array(
							'cluster_uuid' => $cluster_uuid,
							'label'        => null,
						)
					);
					if ( ! $label_cleared ) {
						return new WP_Error( 'acx_db_error', __( 'Could not queue cluster label-clear replay operation.', 'alt-context' ), array( 'status' => 500 ) );
					}

					$cluster_ids[] = $cluster_uuid;
				}

				$result = $wpdb->delete(
					$table_persons,
					array(
						'id'        => $id,
						'tenant_id' => $tenant_id,
					),
					array( '%d', '%s' )
				);
				if ( false === $result ) {
					return new WP_Error(
						'acx_db_error',
						__( 'Could not delete person from database.', 'alt-context' ),
						array( 'status' => 500 )
					);
				}
				if ( 0 === (int) $result ) {
					return new WP_Error(
						'acx_person_not_found',
						__( 'Person not found.', 'alt-context' ),
						array( 'status' => 404 )
					);
				}

				$person_local_revision = max( 1, (int) ( $person->local_revision ?? 0 ) + 1 );
				$queued                = $this->enqueue_curation_operation(
					'person_deleted',
					'person',
					(string) ( $person->person_uuid ?? $id ),
					$person_local_revision,
					array(
						'person_uuid' => (string) ( $person->person_uuid ?? '' ),
						'person_id'   => $id,
					)
				);
				if ( ! $queued ) {
					return new WP_Error( 'acx_db_error', __( 'Could not queue person deletion replay operation.', 'alt-context' ), array( 'status' => 500 ) );
				}

				return rest_ensure_response(
					array(
						'deleted'              => true,
						'id'                   => $id,
						'clusters_dissociated' => count( $cluster_ids ),
						'cluster_ids'          => $cluster_ids,
					)
				);
			}
		);
	}

	/**
	 * @param array<string,mixed> $payload
	 */
	private function enqueue_curation_operation(
		string $operation_type,
		string $entity_type,
		string $entity_key,
		int $local_revision,
		array $payload
	): bool {
		$tenant_id = $this->get_local_tenant_id();
		if ( '' === $tenant_id ) {
			return false;
		}

		$writer = new OutboxWriter();
		$result = $writer->enqueue(
			$tenant_id,
			$operation_type,
			$entity_type,
			$entity_key,
			$this->get_expected_base_version( $tenant_id, $entity_type, $entity_key ),
			max( 0, $local_revision ),
			$payload,
			wp_generate_uuid4()
		);

		return false !== $result;
	}

	private function begin_database_transaction(): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		return false !== $wpdb->query( 'START TRANSACTION' );
	}

	private function commit_database_transaction(): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return false;
		}

		return false !== $wpdb->query( 'COMMIT' );
	}

	private function rollback_database_transaction(): void {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return;
		}

		$wpdb->query( 'ROLLBACK' );
	}

	private function get_person_uuid_by_id( int $person_id, string $table_persons ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$resolved_uuid = $wpdb->get_var(
			$wpdb->prepare( 'SELECT person_uuid FROM %i WHERE id = %d', $table_persons, $person_id )
		);

		return is_string( $resolved_uuid ) && '' !== trim( $resolved_uuid ) ? $resolved_uuid : null;
	}

	private function get_person_name_by_id( int $person_id, string $table_persons ): ?string {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'get_var' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return null;
		}

		$resolved_name = $wpdb->get_var(
			$wpdb->prepare( 'SELECT name FROM %i WHERE id = %d', $table_persons, $person_id )
		);

		return is_string( $resolved_name ) && '' !== trim( $resolved_name ) ? trim( $resolved_name ) : null;
	}

	private function sync_bound_cluster_labels( int $person_id, string $person_name, string $updated_at, string $table_clusters ): bool {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) || ! method_exists( $wpdb, 'prepare' ) ) {
			return false;
		}

		$sql = $wpdb->prepare(
			'UPDATE %i SET label = %s, updated_at = %s, local_revision = local_revision + 1 WHERE person_id = %d',
			$table_clusters,
			trim( $person_name ),
			$updated_at,
			$person_id
		);

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		return false !== $wpdb->query( $sql );
	}

	private function get_local_tenant_id(): string {
		return md5( (string) get_site_url() );
	}

	private function get_expected_base_version( string $tenant_id, string $entity_type, string $entity_key ): int {
		global $wpdb;

		if ( ! isset( $wpdb ) ) {
			return 0;
		}

		if ( 'cluster' === $entity_type ) {
			$table_clusters = $wpdb->prefix . 'acx_clusters';
			$row_version = $wpdb->get_var(
				$wpdb->prepare(
					'SELECT snapshot_version FROM %i WHERE cluster_uuid = %s LIMIT 1',
					$table_clusters,
					$entity_key
				)
			);
			if ( null !== $row_version ) {
				return max( 0, (int) $row_version );
			}
		}

		$table_sync = $wpdb->prefix . 'acx_sync_state';
		$stream_name = sprintf( 'tenant:%s:clusters', trim( $tenant_id ) );
		$version = $wpdb->get_var(
			$wpdb->prepare( 'SELECT last_snapshot_version FROM %i WHERE stream_name = %s LIMIT 1', $table_sync, $stream_name )
		);

		return max( 0, (int) $version );
	}

	public function get_dashboard_stats( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

			$table_persons  = $wpdb->prefix . 'acx_persons';
			$table_clusters = $wpdb->prefix . 'acx_clusters';
			$table_members  = $wpdb->prefix . 'acx_identity_members';

			$people_count = (int) $wpdb->get_var(
				$wpdb->prepare( 'SELECT COUNT(*) FROM %i', $table_persons )
			);

			$assigned_clusters = (int) $wpdb->get_var(
				$wpdb->prepare( 'SELECT COUNT(*) FROM %i WHERE person_id IS NOT NULL', $table_clusters )
			);

			$pending_clusters = (int) $wpdb->get_var(
				$wpdb->prepare(
					'SELECT COUNT(*) FROM %i WHERE person_id IS NULL AND curation_state = %s',
					$table_clusters,
					'uncurated'
				)
			);

			$media_with_faces = (int) $wpdb->get_var(
				$wpdb->prepare( 'SELECT COUNT(DISTINCT attachment_id) FROM %i', $table_members )
			);

			$unassigned_persons = (int) $wpdb->get_var(
				$wpdb->prepare(
					'SELECT COUNT(*) FROM %i p WHERE NOT EXISTS (SELECT 1 FROM %i c WHERE c.person_id = p.id)',
					$table_persons,
					$table_clusters
				)
			);

		return rest_ensure_response(
			array(
				'people_count'             => $people_count,
				'assigned_clusters_count'  => $assigned_clusters,
				'pending_clusters_count'   => $pending_clusters,
				'media_with_faces_count'   => $media_with_faces,
				'unassigned_persons_count' => $unassigned_persons,
			)
		);
	}
}
