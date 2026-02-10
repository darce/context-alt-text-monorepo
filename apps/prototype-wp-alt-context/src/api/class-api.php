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
				$thumb    = wp_get_attachment_image_url( $attachment_id, 'full' );
				$meta     = wp_get_attachment_metadata( $attachment_id );
				$terms    = wp_get_object_terms( $attachment_id, 'post_tag', array( 'fields' => 'names' ) );
				$xmp_persist = get_post_meta( $attachment_id, 'acx_xmp_persist_last_result', true );
				$xmp_persist_payload = is_array( $xmp_persist ) ? $xmp_persist : null;

				return array(
					'id'           => $attachment_id,
					'title'        => get_the_title( $attachment_id ),
					'status'       => '' === trim( (string) $alt_text ) ? 'missing' : 'complete',
					'thumbnailUrl' => false === $thumb ? null : $thumb,
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
				'default'     => 'missing',
				'enum'        => array( 'missing', 'all' ),
			),
		);
	}

	public function get_roster_entries(): WP_REST_Response {
		$entries = get_option( 'acx_roster_entries', array() );
		if ( ! is_array( $entries ) ) {
			$entries = array();
		}

		return rest_ensure_response( $entries );
	}

	public function commit_roster_cluster( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$cluster_id = sanitize_text_field( (string) $request->get_param( 'cluster_id' ) );
		if ( '' === $cluster_id ) {
			return new WP_Error( 'missing_cluster_id', 'Cluster ID is required.', array( 'status' => 400 ) );
		}

		$assignments = get_option( 'acx_roster_assignments', array() );
		if ( ! is_array( $assignments ) ) {
			$assignments = array();
		}

		$entry_id      = $request->get_param( 'roster_entry_id' );
		$new_entry     = $request->get_param( 'new_entry_name' );
		$assignments[ $cluster_id ] = array(
			'roster_entry_id' => null !== $entry_id ? absint( $entry_id ) : null,
			'new_entry_name'  => $new_entry ? sanitize_text_field( (string) $new_entry ) : null,
			'updated_at'      => current_time( 'mysql' ),
		);

		update_option( 'acx_roster_assignments', $assignments );

		return rest_ensure_response(
			array(
				'cluster_id'      => $cluster_id,
				'roster_entry_id' => $assignments[ $cluster_id ]['roster_entry_id'],
				'new_entry_name'  => $assignments[ $cluster_id ]['new_entry_name'],
				'updated_at'      => $assignments[ $cluster_id ]['updated_at'],
			)
		);
	}
}
