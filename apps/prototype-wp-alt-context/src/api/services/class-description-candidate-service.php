<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function absint;
use function array_map;
use function array_slice;
use function array_unique;
use function array_values;
use function basename;
use function get_attached_file;
use function get_post;
use function get_post_meta;
use function get_post_mime_type;
use function get_posts;
use function in_array;
use function is_array;
use function is_object;
use function is_string;
use function json_decode;
use function max;
use function min;
use function sprintf;
use function trim;
use function usort;

class DescriptionCandidateService {
	private const MAX_LIMIT = 100;
	private const DEFAULT_LIMIT = 50;

	/**
	 * @var string[]
	 */
	private const SUPPORTED_IMAGE_MIME_TYPES = array(
		'image/jpeg',
		'image/png',
		'image/webp',
	);

	/**
	 * Partition every attachment into missing-alt candidates and exclusions.
	 *
	 * Preserves the E20-2 REST envelope shape and semantics exactly: the REST
	 * `/recognition/describe/candidates` route depends on this contract. Every
	 * row also carries the unified field set so the CLI consumer can read
	 * `candidate_reason`/`has_alt_text`/`provenance` from the same rows.
	 *
	 * @return array{
	 *   candidates: array<int,array<string,mixed>>,
	 *   exclusions: array<int,array<string,mixed>>,
	 *   limit: int,
	 *   offset: int,
	 *   total_candidates: int,
	 *   total_exclusions: int
	 * }
	 */
	public function list_missing_alt_candidates( int $limit = self::DEFAULT_LIMIT, int $offset = 0 ): array {
		$limit  = $this->normalize_limit( $limit );
		$offset = max( 0, $offset );
		$posts  = get_posts(
			array(
				'post_type'      => 'attachment',
				'post_status'    => 'inherit',
				'posts_per_page' => -1,
				'orderby'        => 'ID',
				'order'          => 'ASC',
			)
		);

		usort(
			$posts,
			static fn ( mixed $left, mixed $right ): int => ( (int) ( $left->ID ?? 0 ) ) <=> ( (int) ( $right->ID ?? 0 ) )
		);

		$candidates = array();
		$exclusions = array();

		foreach ( $posts as $post ) {
			if ( ! is_object( $post ) || ! isset( $post->ID ) ) {
				continue;
			}

			$media_id = (int) $post->ID;
			if ( $media_id <= 0 ) {
				continue;
			}

			$row = $this->build_row( $media_id, $post );
			if ( 'missing_alt' === $row['reason'] ) {
				$candidates[] = $row;
				continue;
			}

			$exclusions[] = $row;
		}

		return array(
			'candidates'       => array_slice( $candidates, $offset, $limit ),
			'exclusions'       => $exclusions,
			'limit'            => $limit,
			'offset'           => $offset,
			'total_candidates' => \count( $candidates ),
			'total_exclusions' => \count( $exclusions ),
		);
	}

	/**
	 * Flat status rows for an explicit set of attachment ids (CLI status/generate).
	 *
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function get_status_for_media_ids( array $media_ids ): array {
		$rows = array();
		foreach ( array_values( array_unique( array_map( 'absint', $media_ids ) ) ) as $media_id ) {
			if ( $media_id <= 0 ) {
				continue;
			}
			$rows[] = $this->build_row( $media_id );
		}

		return $rows;
	}

	private function normalize_limit( int $limit ): int {
		if ( $limit <= 0 ) {
			return self::DEFAULT_LIMIT;
		}
		return min( self::MAX_LIMIT, $limit );
	}

	/**
	 * Unified row builder used by BOTH the REST envelope path and the CLI status
	 * path. Emits the UNION of the fields either consumer relies on. `reason` and
	 * `candidate_reason` always hold the SAME classification value
	 * (`missing_alt|has_alt_text|unsupported_mime|not_found|decorative`). When
	 * `$post` is not supplied it is fetched via `get_post` (used by
	 * `get_status_for_media_ids`).
	 *
	 * Classification order is MECE and stale-marker-proof (WBUX-5-S2C3C-BR-01):
	 *   1. ! is_object( $post )        → not_found
	 *   2. unsupported mime            → unsupported_mime
	 *   3. $has_alt                    → has_alt_text   (wins over leftover marker)
	 *   4. acx_alt_decorative is set   → decorative
	 *   5. otherwise                   → missing_alt
	 * has_alt precedes the marker so a real description is never hidden behind
	 * bookkeeping. Do not add a parallel top-level decorative boolean — reason
	 * is the single source of truth.
	 *
	 * @return array<string,mixed>
	 */
	private function build_row( int $media_id, ?object $post = null ): array {
		if ( null === $post ) {
			$fetched = get_post( $media_id );
			$post    = is_object( $fetched ) ? $fetched : null;
		}

		$mime     = (string) get_post_mime_type( $media_id );
		$path     = get_attached_file( $media_id, true );
		$alt_raw  = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
		$alt_text = is_string( $alt_raw ) ? $alt_raw : '';
		$has_alt  = '' !== trim( $alt_text );

		// Decorative marker: present when meta is the string '1'. Any other
		// value (missing, '', '0') is treated as unset — the write path only
		// plants '1' or deletes the key.
		$decorative_raw = get_post_meta( $media_id, 'acx_alt_decorative', true );
		$is_decorative  = is_string( $decorative_raw ) && '1' === $decorative_raw;

		if ( ! is_object( $post ) ) {
			$reason = 'not_found';
		} elseif ( ! in_array( $mime, self::SUPPORTED_IMAGE_MIME_TYPES, true ) ) {
			$reason = 'unsupported_mime';
		} elseif ( $has_alt ) {
			// Real alt wins over a leftover decorative marker (stale-marker-proof).
			$reason = 'has_alt_text';
		} elseif ( $is_decorative ) {
			$reason = 'decorative';
		} else {
			$reason = 'missing_alt';
		}

		return array(
			'media_id'         => $media_id,
			'filename'         => is_string( $path ) && '' !== $path ? basename( $path ) : sprintf( '%d', $media_id ),
			'title'            => is_object( $post ) && is_string( $post->post_title ?? null ) ? $post->post_title : '',
			'mime_type'        => $mime,
			'current_alt_text' => $alt_text,
			'has_alt_text'     => $has_alt,
			'reason'           => $reason,
			'candidate_reason' => $reason,
			'provenance'       => $this->read_provenance( $media_id ),
		);
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function read_provenance( int $media_id ): ?array {
		$raw = get_post_meta( $media_id, '_acx_description_provenance', true );
		if ( is_array( $raw ) ) {
			return $raw;
		}
		if ( is_string( $raw ) && '' !== trim( $raw ) ) {
			$decoded = json_decode( $raw, true );
			return is_array( $decoded ) ? $decoded : null;
		}

		return null;
	}
}
