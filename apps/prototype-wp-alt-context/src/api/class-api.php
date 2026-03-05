<?php

declare(strict_types=1);

namespace AltContext\Api;

use AltContext\Api\RecognitionController;
use WP_Error;
use WP_Query;
use WP_REST_Request;
use WP_REST_Response;
use function absint;
use function add_action;
use function current_time;
use function current_user_can;
use function get_edit_post_link;
use function get_option;
use function get_post_meta;
use function get_post_mime_type;
use function get_post_modified_time;
use function get_the_title;
use function is_array;
use function is_wp_error;
use function register_rest_route;
use function rest_ensure_response;
use function sanitize_text_field;
use function update_option;
use function wp_get_attachment_image_sizes;
use function wp_get_attachment_image_src;
use function wp_get_attachment_image_srcset;
use function wp_get_attachment_image_url;
use function wp_get_attachment_metadata;
use function wp_get_object_terms;

class Api {
	private RecognitionController $recognitionController;
	private ?XmpEmbedController $xmpEmbedController;

	public function __construct( ?XmpEmbedController $xmp_embed_controller = null ) {
		$this->recognitionController = new RecognitionController();
		$this->xmpEmbedController = $xmp_embed_controller;
	}

	public function init(): void {
		add_action( 'rest_api_init', array( $this, 'register_routes' ) );
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
			$args['meta_query'] = array(
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
			);
		}

		$query       = new WP_Query( $args );
		$attachments = $query->posts;

		$items = array_map(
			function ( int $attachment_id ): array {
				$alt_text = get_post_meta( $attachment_id, '_wp_attachment_image_alt', true );
				$thumb_medium = wp_get_attachment_image_src( $attachment_id, 'medium' );
				$thumb_url    = wp_get_attachment_image_url( $attachment_id, 'full' );
				$thumb        = is_array( $thumb_medium ) && isset( $thumb_medium[0] ) ? $thumb_medium[0] : $thumb_url;
				$thumb_width  = is_array( $thumb_medium ) && isset( $thumb_medium[1] ) ? (int) $thumb_medium[1] : null;
				$thumb_height = is_array( $thumb_medium ) && isset( $thumb_medium[2] ) ? (int) $thumb_medium[2] : null;
				$thumb_srcset = wp_get_attachment_image_srcset( $attachment_id, 'medium' );
				$thumb_sizes  = wp_get_attachment_image_sizes( $attachment_id, 'medium' );
				$meta     = wp_get_attachment_metadata( $attachment_id );
				$terms    = wp_get_object_terms( $attachment_id, 'post_tag', array( 'fields' => 'names' ) );
				$xmp_persist = get_post_meta( $attachment_id, 'acx_xmp_persist_last_result', true );
				$xmp_persist_payload = is_array( $xmp_persist ) ? $xmp_persist : null;

				return array(
					'id'           => $attachment_id,
					'title'        => get_the_title( $attachment_id ),
					'status'       => '' === trim( (string) $alt_text ) ? 'missing' : 'complete',
					'thumbnailUrl' => false === $thumb ? null : $thumb,
					'thumbnailSrcset' => is_string( $thumb_srcset ) ? $thumb_srcset : null,
					'thumbnailSizes'  => is_string( $thumb_sizes ) ? $thumb_sizes : null,
					'thumbnailDimensions' => array(
						'width'  => $thumb_width,
						'height' => $thumb_height,
					),
					'altText'      => '' === trim( (string) $alt_text ) ? null : $alt_text,
					'mimeType'     => get_post_mime_type( $attachment_id ),
					'editUrl'      => get_edit_post_link( $attachment_id, '' ),
					'updatedAt'    => get_post_modified_time( 'c', true, $attachment_id ),
					'dimensions'   => array(
						'width'  => isset( $meta['width'] ) ? (int) $meta['width'] : null,
						'height' => isset( $meta['height'] ) ? (int) $meta['height'] : null,
					),
					'xmpPersistence' => $xmp_persist_payload,
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

	public function get_roster_entries( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$table_persons  = $wpdb->prefix . 'acx_persons';
		$table_clusters = $wpdb->prefix . 'acx_clusters';
		$results = $wpdb->get_results(
			$wpdb->prepare(
				'SELECT p.*, (SELECT COUNT(*) FROM %i c WHERE c.person_id = p.id) AS cluster_count FROM %i p ORDER BY p.name ASC',
				$table_clusters,
				$table_persons
			),
			ARRAY_A
		);

		if ( ! is_array( $results ) ) {
			return rest_ensure_response( array() );
		}

		// Decode tags for each person
		$entries = array_map(
			function ( $row ) {
				if ( isset( $row['tags'] ) && is_string( $row['tags'] ) ) {
					$decoded     = json_decode( $row['tags'], true );
					$row['tags'] = is_array( $decoded ) ? $decoded : array();
				}
				$row['cluster_count'] = isset( $row['cluster_count'] ) ? (int) $row['cluster_count'] : 0;
				return $row;
			},
			$results
		);

		return rest_ensure_response( $entries );
	}

	public function commit_roster_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$person_id = $request->get_param( 'roster_entry_id' );
		$new_name  = $request->get_param( 'new_entry_name' );

		// If new name provided, create person first
		if ( ! $person_id && $new_name ) {
			$new_name = sanitize_text_field( (string) $new_name );
			if ( ! empty( trim( $new_name ) ) ) {
				$table_persons = $wpdb->prefix . 'acx_persons';
				$existing_id   = $wpdb->get_var( $wpdb->prepare( 'SELECT id FROM %i WHERE name = %s', $table_persons, $new_name ) );

				if ( $existing_id ) {
					$person_id = (int) $existing_id;
				} else {
					$person_uuid = wp_generate_uuid4();
					$now         = current_time( 'mysql' );
					$inserted    = $wpdb->insert(
						$table_persons,
						array(
							'person_uuid' => $person_uuid,
							'name'        => $new_name,
							'tags'        => wp_json_encode( array() ),
							'created_at'  => $now,
							'updated_at'  => $now,
						)
					);
					if ( $inserted ) {
						$person_id = $wpdb->insert_id;
					}
				}
			}
		}

		$person_id = $person_id ? absint( $person_id ) : null;

		// Update cluster projection
		$table_clusters = $wpdb->prefix . 'acx_clusters';

		$update_data = array( 'person_id' => $person_id );
		$update_fmt  = array( '%d' );

		if ( null === $person_id ) {
			$update_fmt = array( null );
		}

		$wpdb->update(
			$table_clusters,
			$update_data,
			array( 'cluster_uuid' => $cluster_id ),
			$update_fmt,
			array( '%s' )
		);

		return rest_ensure_response(
			array(
				'cluster_id' => $cluster_id,
				'person_id'  => $person_id,
				'updated_at' => current_time( 'mysql' ),
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

			// Check for existing name
			$table_name = $wpdb->prefix . 'acx_persons';
			$existing   = $wpdb->get_var( $wpdb->prepare( 'SELECT id FROM %i WHERE name = %s', $table_name, $name ) );
		if ( $existing ) {
			return new WP_Error( 'acx_person_exists', __( 'A person with this name already exists.', 'alt-context' ), array( 'status' => 409 ) );
		}

		$person_uuid = wp_generate_uuid4();
		$now         = current_time( 'mysql' );

		$result = $wpdb->insert(
			$table_name,
			array(
				'person_uuid' => $person_uuid,
				'name'        => $name,
				'tags'        => wp_json_encode( $tags ),
				'created_at'  => $now,
				'updated_at'  => $now,
			),
			array( '%s', '%s', '%s', '%s', '%s' )
		);

		if ( false === $result ) {
			return new WP_Error( 'acx_db_error', __( 'Could not create person in database.', 'alt-context' ), array( 'status' => 500 ) );
		}

		$person_id = $wpdb->insert_id;

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

			$table_name = $wpdb->prefix . 'acx_persons';
			$person     = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d', $table_name, $id ) );

		if ( ! $person ) {
			return new WP_Error( 'acx_person_not_found', __( 'Person not found.', 'alt-context' ), array( 'status' => 404 ) );
		}

		$update_data = array();
		$update_fmt  = array();

		if ( null !== $name ) {
			$name = sanitize_text_field( (string) $name );
				// Check for conflict if name changed
			if ( $name !== $person->name ) {
				$conflict = $wpdb->get_var( $wpdb->prepare( 'SELECT id FROM %i WHERE name = %s AND id != %d', $table_name, $name, $id ) );
				if ( $conflict ) {
					return new WP_Error( 'acx_person_exists', __( 'Another person with this name already exists.', 'alt-context' ), array( 'status' => 409 ) );
				}
				$update_data['name'] = $name;
				$update_fmt[]        = '%s';
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

		$result = $wpdb->update( $table_name, $update_data, array( 'id' => $id ), $update_fmt, array( '%d' ) );

		if ( false === $result ) {
			return new WP_Error( 'acx_db_error', __( 'Could not update person in database.', 'alt-context' ), array( 'status' => 500 ) );
		}

			$updated_person = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d', $table_name, $id ) );
		if ( isset( $updated_person->tags ) && is_string( $updated_person->tags ) ) {
			$updated_person->tags = json_decode( $updated_person->tags, true );
		}

		return rest_ensure_response( $updated_person );
	}

	public function delete_person( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		global $wpdb;

		$id = (int) $request->get_param( 'id' );

			$table_persons  = $wpdb->prefix . 'acx_persons';
			$table_clusters = $wpdb->prefix . 'acx_clusters';

			$person = $wpdb->get_row( $wpdb->prepare( 'SELECT * FROM %i WHERE id = %d', $table_persons, $id ) );
		if ( ! $person ) {
			return new WP_Error( 'acx_person_not_found', __( 'Person not found.', 'alt-context' ), array( 'status' => 404 ) );
		}

		// Soft dissociation: nullify person_id on assigned clusters
		$wpdb->update(
			$table_clusters,
			array( 'person_id' => null ),
			array( 'person_id' => $id ),
			array( null ),
			array( '%d' )
		);

		$result = $wpdb->delete( $table_persons, array( 'id' => $id ), array( '%d' ) );

		if ( false === $result ) {
			return new WP_Error( 'acx_db_error', __( 'Could not delete person from database.', 'alt-context' ), array( 'status' => 500 ) );
		}

		return rest_ensure_response( array( 'deleted' => true, 'id' => $id ) );
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
				$wpdb->prepare( 'SELECT COUNT(DISTINCT media_id) FROM %i', $table_members )
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
