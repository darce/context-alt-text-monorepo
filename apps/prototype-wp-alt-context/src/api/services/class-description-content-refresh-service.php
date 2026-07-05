<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function absint;
use function array_values;
use function count;
use function get_post_meta;
use function get_posts;
use function html_entity_decode;
use function is_array;
use function is_object;
use function preg_match;
use function preg_match_all;
use function sprintf;
use function trim;

/**
 * Discovers posts/pages whose embedded image alt text can be refreshed safely.
 */
class DescriptionContentRefreshService {
	private const ALT_META = '_wp_attachment_image_alt';

	/**
	 * @param int[] $media_ids
	 * @return array<string,mixed>
	 */
	public function dry_run( array $media_ids, int $limit = 50 ): array {
		$media_ids = $this->normalize_media_ids( $media_ids );
		$posts     = $this->load_candidate_posts( $limit );

		$candidates = array();
		$skipped    = array();

		foreach ( $posts as $post ) {
			if ( ! is_object( $post ) || ! isset( $post->ID, $post->post_content ) ) {
				continue;
			}

			$post_id = absint( $post->ID );
			$content = (string) $post->post_content;

			foreach ( $media_ids as $media_id ) {
				$current_alt_text = trim( (string) get_post_meta( $media_id, self::ALT_META, true ) );
				if ( '' === $current_alt_text ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'missing_current_alt_text' );
					continue;
				}

				$matches = $this->find_image_tags_for_media( $content, $media_id );
				if ( 0 === count( $matches ) ) {
					continue;
				}

				if ( count( $matches ) > 1 ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'ambiguous_multiple_references' );
					continue;
				}

				$existing_alt_text = $this->extract_alt_text( $matches[0] );
				if ( null === $existing_alt_text ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'missing_embedded_alt_text' );
					continue;
				}

				if ( $existing_alt_text === $current_alt_text ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'already_current' );
					continue;
				}

				$candidates[] = array(
					'post_id'           => $post_id,
					'post_type'         => isset( $post->post_type ) ? (string) $post->post_type : '',
					'post_title'        => isset( $post->post_title ) ? (string) $post->post_title : '',
					'media_id'          => $media_id,
					'existing_alt_text' => $existing_alt_text,
					'current_alt_text'  => $current_alt_text,
				);
			}
		}

		return array(
			'summary'    => array(
				'dry_run'       => true,
				'scanned_posts' => count( $posts ),
				'media_ids'     => count( $media_ids ),
				'candidates'    => count( $candidates ),
				'skipped'       => count( $skipped ),
			),
			'candidates' => $candidates,
			'skipped'    => $skipped,
		);
	}

	/**
	 * @param int[] $media_ids
	 * @return int[]
	 */
	private function normalize_media_ids( array $media_ids ): array {
		$normalized = array();
		foreach ( $media_ids as $media_id ) {
			$value = absint( $media_id );
			if ( $value > 0 ) {
				$normalized[ $value ] = $value;
			}
		}

		return array_values( $normalized );
	}

	/**
	 * @return array<int,mixed>
	 */
	private function load_candidate_posts( int $limit ): array {
		$posts = get_posts(
			array(
				'post_type'      => array( 'post', 'page', 'product' ),
				'post_status'    => array( 'publish', 'draft', 'private', 'future' ),
				'posts_per_page' => max( 1, $limit ),
				'orderby'        => 'ID',
				'order'          => 'DESC',
			)
		);

		return is_array( $posts ) ? $posts : array();
	}

	/**
	 * @return string[]
	 */
	private function find_image_tags_for_media( string $content, int $media_id ): array {
		$pattern = sprintf( '/<img\b[^>]*\bwp-image-%d\b[^>]*>/i', $media_id );
		if ( false === preg_match_all( $pattern, $content, $matches ) ) {
			return array();
		}

		return $matches[0];
	}

	private function extract_alt_text( string $image_tag ): ?string {
		if ( 1 !== preg_match( '/\salt\s*=\s*([\'"])(.*?)\1/i', $image_tag, $matches ) ) {
			return null;
		}

		return html_entity_decode( (string) $matches[2], ENT_QUOTES );
	}

	/**
	 * @return array<string,mixed>
	 */
	private function build_skip( object $post, int $media_id, string $reason ): array {
		return array(
			'post_id'    => isset( $post->ID ) ? absint( $post->ID ) : 0,
			'post_type'  => isset( $post->post_type ) ? (string) $post->post_type : '',
			'post_title' => isset( $post->post_title ) ? (string) $post->post_title : '',
			'media_id'   => $media_id,
			'reason'     => $reason,
		);
	}
}
