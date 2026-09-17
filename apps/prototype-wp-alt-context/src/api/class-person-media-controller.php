<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/class-tenant-identity.php';
require_once __DIR__ . '/class-blob-url-rewriter.php';
require_once dirname( __DIR__ ) . '/sovereign/class-projection-query-exception.php';
require_once dirname( __DIR__ ) . '/sovereign/repositories/trait-prepares-sql-queries.php';
require_once dirname( __DIR__ ) . '/sovereign/repositories/class-identity-members-read-repository.php';

use AltContext\Sovereign\ProjectionQueryException;
use AltContext\Sovereign\Repositories\IdentityMembersReadRepository;
use AltContext\Sovereign\Repositories\PreparesSqlQueries;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function count;
use function filter_var;
use function is_array;
use function is_int;
use function is_numeric;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function method_exists;
use function preg_match;
use function register_rest_route;
use function trim;
use function wp_get_attachment_url;

interface PersonMediaRowsSource {
	/**
	 * Paged identity-member rows for one person. Each row must carry
	 * `total_count` from the query window (rg-015); never derive total from
	 * PHP `count()`.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function list_projected_cluster_rows_by_person( string $tenant_id, int $person_id, int $limit, int $offset ): array;
}

/**
 * Default read adapter: IdentityMembersReadRepository tables, windowed page.
 */
final class IdentityMembersPersonMediaReadRepository extends IdentityMembersReadRepository implements PersonMediaRowsSource {
	use PreparesSqlQueries;

	public function list_projected_cluster_rows_by_person( string $tenant_id, int $person_id, int $limit, int $offset ): array {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		if ( '' === $normalized_tenant_id || ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_results' ) ) {
			throw new ProjectionQueryException( 'Projection query failed [identity_members.list_projected_cluster_rows_by_person]: wpdb is unavailable' );
		}

		$prefix = ( isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) ? $wpdb->prefix : 'wp_';
		$sql    = $this->prepare_query(
			'SELECT COUNT(*) OVER() AS total_count, m.identity_uuid, m.attachment_id, m.cluster_uuid, m.bbox_json, m.thumb_path, m.similarity
			FROM %i m
			INNER JOIN %i c ON c.cluster_uuid = m.cluster_uuid
			WHERE c.tenant_id = %s AND c.person_id = %d
			ORDER BY m.assigned_at ASC, m.identity_uuid LIMIT %d OFFSET %d',
			array(
				$prefix . 'acx_identity_members',
				$prefix . 'acx_clusters',
				$normalized_tenant_id,
				$person_id,
				$limit,
				$offset,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			throw new ProjectionQueryException( 'Projection query failed [identity_members.list_projected_cluster_rows_by_person]: wpdb could not prepare query' );
		}

		$wpdb->last_error = '';
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$rows = $wpdb->get_results( $sql, ARRAY_A );
		$error = isset( $wpdb->last_error ) && is_string( $wpdb->last_error ) ? trim( $wpdb->last_error ) : '';
		if ( '' !== $error ) {
			$wpdb->last_error = '';
			throw new ProjectionQueryException( 'Projection query failed [identity_members.list_projected_cluster_rows_by_person]: ' . $error );
		}
		if ( ! is_array( $rows ) ) {
			throw new ProjectionQueryException( 'Projection query failed [identity_members.list_projected_cluster_rows_by_person]: query did not execute (wpdb not ready or query filtered)' );
		}

		return $rows;
	}
}

class PersonMediaController {
	use PreparesSqlQueries;

	public const DEFAULT_LIMIT = 50;
	public const MAX_LIMIT     = 500;

	private PersonMediaRowsSource $members;

	public function __construct( ?PersonMediaRowsSource $members = null ) {
		global $wpdb;

		$prefix = 'wp_';
		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			$prefix = $wpdb->prefix;
		}

		$this->members = $members ?? new IdentityMembersPersonMediaReadRepository(
			$prefix . 'acx_identity_members',
			$prefix . 'acx_clusters'
		);
	}

	public function register_routes( callable $permission ): void {
		register_rest_route(
			'acx/v1',
			'/roster/persons/(?P<id>[1-9][0-9]*)/media',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_media' ),
				'permission_callback' => $permission,
				'args'                => array(
					'limit'  => array(
						'description' => 'Maximum media rows to return.',
						'type'        => 'integer',
						'required'    => false,
					),
					'offset' => array(
						'description' => 'Number of media rows to skip.',
						'type'        => 'integer',
						'required'    => false,
					),
				),
			)
		);
	}

	public function get_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$person_id = $this->resolve_person_id( $request );
		if ( $person_id instanceof WP_Error ) {
			return $person_id;
		}

		$limit = $this->resolve_limit( $request );
		if ( $limit instanceof WP_Error ) {
			return $limit;
		}

		$offset = $this->resolve_offset( $request );
		if ( $offset instanceof WP_Error ) {
			return $offset;
		}

		$tenant_id = TenantIdentity::resolve()['value'] ?? '';
		if ( ! is_string( $tenant_id ) || '' === trim( $tenant_id ) ) {
			return new WP_Error( 'acx_db_error', 'Tenant identity is unavailable.', array( 'status' => 500 ) );
		}
		$tenant_id = trim( $tenant_id );

		$person = $this->find_person_for_tenant( $tenant_id, $person_id );
		if ( $person instanceof WP_Error ) {
			return $person;
		}
		if ( null === $person ) {
			return new WP_Error( 'acx_person_not_found', 'Person not found.', array( 'status' => 404 ) );
		}

		try {
			$rows = $this->members->list_projected_cluster_rows_by_person( $tenant_id, $person_id, $limit, $offset );
		} catch ( ProjectionQueryException ) {
			return ProjectionQueryException::to_rest_error( 'get_person_media' );
		}

		if ( ! is_array( $rows ) ) {
			$rows = array();
		}

		$total = $this->resolve_total_from_query( $rows, $offset );
		if ( $total instanceof WP_Error ) {
			return $total;
		}

		$media = array();
		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}
			$media[] = $this->map_media_item( $row );
		}

		return new WP_REST_Response(
			array(
				'media'     => $media,
				'limit'     => $limit,
				'offset'    => $offset,
				'total'     => $total,
				'truncated' => ( $offset + count( $media ) ) < $total,
			),
			200
		);
	}

	private function resolve_person_id( WP_REST_Request $request ): int|WP_Error {
		$value = $request->get_param( 'id' );
		if ( ( ! is_int( $value ) && ! is_string( $value ) ) || ! preg_match( '/^[1-9][0-9]*$/D', (string) $value ) || false === filter_var( $value, FILTER_VALIDATE_INT ) ) {
			return new WP_Error( 'invalid_person_id', 'A positive integer person ID is required.', array( 'status' => 400 ) );
		}

		return (int) $value;
	}

	private function resolve_limit( WP_REST_Request $request ): int|WP_Error {
		$raw = $request->get_param( 'limit' );
		if ( null === $raw || '' === $raw ) {
			return self::DEFAULT_LIMIT;
		}

		if ( ! is_numeric( $raw ) || (int) $raw < 1 || (int) $raw > self::MAX_LIMIT ) {
			return new WP_Error( 'invalid_limit', 'limit out of range', array( 'status' => 400 ) );
		}

		return absint( $raw );
	}

	private function resolve_offset( WP_REST_Request $request ): int|WP_Error {
		$raw = $request->get_param( 'offset' );
		if ( null === $raw || '' === $raw ) {
			return 0;
		}

		if ( ! is_numeric( $raw ) || (int) $raw < 0 ) {
			return new WP_Error( 'invalid_offset', 'offset must be non-negative', array( 'status' => 400 ) );
		}

		return absint( $raw );
	}

	/**
	 * @return array<string,mixed>|null|WP_Error
	 */
	private function find_person_for_tenant( string $tenant_id, int $person_id ): array|null|WP_Error {
		global $wpdb;

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'prepare' ) || ! method_exists( $wpdb, 'get_row' ) ) {
			return new WP_Error( 'acx_db_error', 'Database is unavailable.', array( 'status' => 500 ) );
		}

		$prefix = ( isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) ? $wpdb->prefix : 'wp_';
		$sql    = $this->prepare_query(
			'SELECT id FROM %i WHERE id = %d AND tenant_id = %s',
			array(
				$prefix . 'acx_persons',
				$person_id,
				$tenant_id,
			)
		);
		if ( ! is_string( $sql ) || '' === $sql ) {
			return new WP_Error( 'acx_db_error', 'Database is unavailable.', array( 'status' => 500 ) );
		}

		$wpdb->last_error = '';
		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$row   = $wpdb->get_row( $sql, ARRAY_A );
		$error = isset( $wpdb->last_error ) && is_string( $wpdb->last_error ) ? trim( $wpdb->last_error ) : '';
		if ( '' !== $error ) {
			$wpdb->last_error = '';
			return ProjectionQueryException::to_rest_error( 'get_person_media' );
		}

		return is_array( $row ) ? $row : null;
	}

	/**
	 * @param array<int,mixed> $rows
	 */
	private function resolve_total_from_query( array $rows, int $offset ): int|WP_Error {
		if ( isset( $rows[0] ) && is_array( $rows[0] ) && isset( $rows[0]['total_count'] ) && is_numeric( $rows[0]['total_count'] ) ) {
			return max( 0, (int) $rows[0]['total_count'] );
		}

		// Empty first page has no window row; zero is the query result, not PHP count().
		if ( array() === $rows && 0 === $offset ) {
			return 0;
		}

		return new WP_Error(
			'invalid_person_media_envelope',
			'Person media response must include query total_count; page length is not total.',
			array( 'status' => 502 )
		);
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array{identity_id:string,media_id:int,media_url:?string,bbox:?array{x:int,y:int,width:int,height:int},similarity:?float,cluster_id:string}
	 */
	private function map_media_item( array $row ): array {
		$identity_id = trim( (string) ( $row['identity_id'] ?? $row['identity_uuid'] ?? '' ) );
		$cluster_id  = trim( (string) ( $row['cluster_id'] ?? $row['cluster_uuid'] ?? '' ) );
		$media_id    = absint( $row['media_id'] ?? $row['attachment_id'] ?? 0 );

		$similarity = null;
		if ( isset( $row['similarity'] ) && '' !== trim( (string) $row['similarity'] ) && is_numeric( $row['similarity'] ) ) {
			$similarity = (float) $row['similarity'];
		}

		$resolved = $this->resolve_media_and_bbox( $row, $media_id );

		return array(
			'identity_id' => $identity_id,
			'media_id'    => $media_id,
			'media_url'   => $resolved['media_url'],
			'bbox'        => $resolved['bbox'],
			'similarity'  => $similarity,
			'cluster_id'  => $cluster_id,
		);
	}

	/**
	 * Resolve media_url and bbox as one pair (original_image space only).
	 *
	 * Bbox is emitted only when media_url came from wp_get_attachment_url
	 * (or an explicit original media_url). On the thumb_path fallback path
	 * bbox is always null — the stored thumb is not original_image space.
	 *
	 * @param array<string,mixed> $row
	 * @return array{media_url:?string,bbox:?array{x:int,y:int,width:int,height:int}}
	 */
	private function resolve_media_and_bbox( array $row, int $media_id ): array {
		if ( isset( $row['media_url'] ) && is_string( $row['media_url'] ) && '' !== trim( $row['media_url'] ) ) {
			return array(
				'media_url' => $row['media_url'],
				'bbox'      => $this->extract_bbox( $row ),
			);
		}

		if ( $media_id > 0 ) {
			$attachment_url = wp_get_attachment_url( $media_id );
			if ( is_string( $attachment_url ) && '' !== trim( $attachment_url ) ) {
				return array(
					'media_url' => $attachment_url,
					'bbox'      => $this->extract_bbox( $row ),
				);
			}
		}

		return array(
			'media_url' => $this->resolve_thumb_path_media_url( $row ),
			'bbox'      => null,
		);
	}

	/**
	 * @param array<string,mixed> $row
	 */
	private function resolve_thumb_path_media_url( array $row ): ?string {
		$thumb_path = isset( $row['thumb_path'] ) ? trim( (string) $row['thumb_path'] ) : '';
		if ( '' === $thumb_path ) {
			return null;
		}

		$rewritten = BlobUrlRewriter::rewrite_string( $thumb_path );
		if ( '' === trim( $rewritten ) ) {
			return null;
		}

		if ( $rewritten !== $thumb_path || str_starts_with( $rewritten, 'http://' ) || str_starts_with( $rewritten, 'https://' ) || str_starts_with( $rewritten, '/' ) ) {
			return $rewritten;
		}

		return null;
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array{x:int,y:int,width:int,height:int}|null
	 */
	private function extract_bbox( array $row ): ?array {
		if ( isset( $row['bbox'] ) && is_array( $row['bbox'] ) ) {
			return $this->normalize_bbox( $row['bbox'] );
		}

		return $this->extract_bbox_pixels( $row['bbox_json'] ?? null );
	}

	/**
	 * @param mixed $bbox_json
	 * @return array{x:int,y:int,width:int,height:int}|null
	 */
	private function extract_bbox_pixels( mixed $bbox_json ): ?array {
		if ( ! is_string( $bbox_json ) || '' === trim( $bbox_json ) ) {
			return null;
		}

		$decoded = json_decode( $bbox_json, true );
		if ( ! is_array( $decoded ) ) {
			return null;
		}

		$pixels = $decoded['pixels'] ?? $decoded;
		if ( ! is_array( $pixels ) ) {
			return null;
		}

		return $this->normalize_bbox( $pixels );
	}

	/**
	 * @param array<string,mixed> $pixels
	 * @return array{x:int,y:int,width:int,height:int}|null
	 */
	private function normalize_bbox( array $pixels ): ?array {
		$rect = array(
			'x'      => absint( $pixels['x'] ?? 0 ),
			'y'      => absint( $pixels['y'] ?? 0 ),
			'width'  => absint( $pixels['width'] ?? 0 ),
			'height' => absint( $pixels['height'] ?? 0 ),
		);

		if ( $rect['width'] <= 0 || $rect['height'] <= 0 ) {
			return null;
		}

		return $rect;
	}
}
