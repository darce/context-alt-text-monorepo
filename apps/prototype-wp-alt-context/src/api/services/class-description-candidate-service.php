<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function array_slice;
use function basename;
use function get_attached_file;
use function get_post_meta;
use function get_post_mime_type;
use function get_posts;
use function in_array;
use function is_object;
use function is_string;
use function max;
use function min;
use function sprintf;
use function trim;
use function usort;

class DescriptionCandidateService {
	private const MAX_LIMIT = 100;
	private const DEFAULT_LIMIT = 50;
	private const SUPPORTED_IMAGE_MIME_TYPES = array(
		'image/jpeg',
		'image/png',
		'image/webp',
	);

	/**
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

			$row = $this->build_base_row( $media_id, $post );
			if ( ! in_array( $row['mime_type'], self::SUPPORTED_IMAGE_MIME_TYPES, true ) ) {
				$row['reason'] = 'unsupported_mime';
				$exclusions[]  = $row;
				continue;
			}

			if ( '' !== trim( $row['current_alt_text'] ) ) {
				$row['reason'] = 'has_alt_text';
				$exclusions[]  = $row;
				continue;
			}

			$row['reason'] = 'missing_alt';
			$candidates[]  = $row;
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

	private function normalize_limit( int $limit ): int {
		if ( $limit <= 0 ) {
			return self::DEFAULT_LIMIT;
		}
		return min( self::MAX_LIMIT, $limit );
	}

	/**
	 * @return array<string,mixed>
	 */
	private function build_base_row( int $media_id, object $post ): array {
		$path = get_attached_file( $media_id, true );
		$alt  = get_post_meta( $media_id, '_wp_attachment_image_alt', true );

		return array(
			'media_id'         => $media_id,
			'filename'         => is_string( $path ) && '' !== $path ? basename( $path ) : sprintf( '%d', $media_id ),
			'title'            => is_string( $post->post_title ?? null ) ? $post->post_title : '',
			'mime_type'        => (string) get_post_mime_type( $media_id ),
			'current_alt_text' => is_string( $alt ) ? $alt : '',
		);
	}
}
