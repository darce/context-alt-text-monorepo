<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function absint;
use function array_map;
use function array_slice;
use function array_values;
use function get_post;
use function get_post_meta;
use function get_post_mime_type;
use function get_posts;
use function in_array;
use function is_array;
use function is_object;
use function json_decode;
use function trim;

class DescriptionCandidateService {
	private const MAX_LIMIT = 100;

	/**
	 * @var string[]
	 */
	private const SUPPORTED_MIME_TYPES = array(
		'image/jpeg',
		'image/png',
		'image/webp',
	);

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function list_missing_alt_candidates( int $limit = 50, int $offset = 0 ): array {
		$limit  = $this->normalize_limit( $limit );
		$offset = max( 0, $offset );

		$ids = get_posts(
			array(
				'post_type'      => 'attachment',
				'post_status'    => 'inherit',
				'post_mime_type' => 'image',
				'fields'         => 'ids',
				'posts_per_page' => -1,
				'orderby'        => 'ID',
				'order'          => 'ASC',
			)
		);

		if ( ! is_array( $ids ) ) {
			return array();
		}

		$rows = array();
		foreach ( $ids as $id ) {
			$row = $this->build_status_row( absint( $id ) );
			if ( 'missing_alt' === $row['candidate_reason'] ) {
				$rows[] = $row;
			}
		}

		return array_values( array_slice( $rows, $offset, $limit ) );
	}

	/**
	 * @param int[] $media_ids
	 * @return array<int,array<string,mixed>>
	 */
	public function get_status_for_media_ids( array $media_ids ): array {
		$rows = array();
		foreach ( array_values( array_unique( array_map( 'absint', $media_ids ) ) ) as $media_id ) {
			if ( $media_id <= 0 ) {
				continue;
			}
			$rows[] = $this->build_status_row( $media_id );
		}

		return $rows;
	}

	/**
	 * @return array<string,mixed>
	 */
	private function build_status_row( int $media_id ): array {
		$post     = get_post( $media_id );
		$mime     = (string) get_post_mime_type( $media_id );
		$alt_text = trim( (string) get_post_meta( $media_id, '_wp_attachment_image_alt', true ) );

		$reason = 'missing_alt';
		if ( ! is_object( $post ) ) {
			$reason = 'not_found';
		} elseif ( ! in_array( $mime, self::SUPPORTED_MIME_TYPES, true ) ) {
			$reason = 'unsupported_mime';
		} elseif ( '' !== $alt_text ) {
			$reason = 'has_alt_text';
		}

		return array(
			'media_id'         => $media_id,
			'title'            => is_object( $post ) && isset( $post->post_title ) ? (string) $post->post_title : '',
			'mime_type'        => $mime,
			'has_alt_text'     => '' !== $alt_text,
			'candidate_reason' => $reason,
			'provenance'       => $this->read_provenance( $media_id ),
		);
	}

	private function normalize_limit( int $limit ): int {
		if ( $limit < 1 ) {
			return 1;
		}

		return min( self::MAX_LIMIT, $limit );
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
