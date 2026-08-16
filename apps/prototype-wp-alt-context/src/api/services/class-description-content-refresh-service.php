<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function absint;
use function array_merge;
use function array_values;
use function count;
use function get_post;
use function get_post_meta;
use function get_posts;
use function html_entity_decode;
use function is_array;
use function is_object;
use function is_string;
use function is_wp_error;
use function json_decode;
use function json_encode;
use function preg_match;
use function preg_match_all;
use function preg_replace;
use function preg_replace_callback;
use function sprintf;
use function trim;
use function wp_update_post;

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
				$matches = $this->find_image_tags_for_media( $content, $media_id );
				if ( 0 === count( $matches ) ) {
					continue;
				}

				// Meta is entity-encoded (sanitize_text_field); compare decoded.
				$current_alt_text = trim(
					html_entity_decode( (string) get_post_meta( $media_id, self::ALT_META, true ), ENT_QUOTES )
				);
				if ( '' === $current_alt_text ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'missing_current_alt_text' );
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
	 * @return array<string,mixed>
	 */
	public function apply( array $media_ids, int $limit = 50 ): array {
		$media_ids = $this->normalize_media_ids( $media_ids );
		$posts     = $this->load_candidate_posts( $limit );

		$changed    = array();
		$failed     = array();
		$skipped    = array();
		$candidates = 0;

		foreach ( $posts as $post ) {
			if ( ! is_object( $post ) || ! isset( $post->ID, $post->post_content ) ) {
				continue;
			}

			$content         = (string) $post->post_content;
			$updated_content = $content;
			// Accumulate intended per-media changes; promote to $changed only
			// after wp_update_post is verified (BR-08).
			$pending_changed = array();

			foreach ( $media_ids as $media_id ) {
				$matches = $this->find_image_tags_for_media( $updated_content, $media_id );
				if ( 0 === count( $matches ) ) {
					continue;
				}

				// Meta is entity-encoded (sanitize_text_field); compare and write decoded.
				$current_alt_text = trim(
					html_entity_decode( (string) get_post_meta( $media_id, self::ALT_META, true ), ENT_QUOTES )
				);
				if ( '' === $current_alt_text ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'missing_current_alt_text' );
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

				// $current_alt_text is decoded; esc_attr re-encodes for HTML alt,
				// and replace_block_alt_attributes needs real characters for JSON.
				$updated_tag = $this->replace_alt_text( $matches[0], $current_alt_text );
				if ( $updated_tag === $matches[0] ) {
					$skipped[] = $this->build_skip( $post, $media_id, 'replacement_failed' );
					continue;
				}

				$updated_content   = $this->replace_once( $updated_content, $matches[0], $updated_tag );
				$updated_content   = $this->replace_block_alt_attributes( $updated_content, $media_id, $current_alt_text );
				$pending_changed[] = array(
					'post_id'           => absint( $post->ID ),
					'post_type'         => isset( $post->post_type ) ? (string) $post->post_type : '',
					'post_title'        => isset( $post->post_title ) ? (string) $post->post_title : '',
					'media_id'          => $media_id,
					'existing_alt_text' => $existing_alt_text,
					'current_alt_text'  => $current_alt_text,
				);
			}

			if ( $updated_content !== $content ) {
				// candidates = intended writes; changed = verified durable writes.
				$candidates += count( $pending_changed );
				$post_id     = absint( $post->ID );
				$updated     = wp_update_post(
					array(
						'ID'           => $post_id,
						'post_content' => $updated_content,
					),
					true
				);
				if ( is_wp_error( $updated ) || 0 === $updated || false === $updated ) {
					foreach ( $pending_changed as $entry ) {
						$failed[] = array_merge(
							$entry,
							array( 'reason' => 'post_update_failed' )
						);
					}
				} else {
					// wp_update_post → wp_insert_post returns the post ID even when
					// wp_insert_post_data / content_save_pre / kses altered the bytes.
					// Read back durable storage per consumer accessor; verify each
					// intended alt actually landed (R16-BR-13 / rg-015).
					$stored_post    = get_post( $post_id );
					$stored_content = ( is_object( $stored_post ) && isset( $stored_post->post_content ) )
						? (string) $stored_post->post_content
						: '';
					foreach ( $pending_changed as $entry ) {
						$media_id     = absint( $entry['media_id'] );
						$intended_alt = (string) $entry['current_alt_text'];
						if ( $this->stored_content_has_intended_alt( $stored_content, $media_id, $intended_alt ) ) {
							$changed[] = $entry;
						} else {
							$failed[] = array_merge(
								$entry,
								array( 'reason' => 'post_content_not_persisted' )
							);
						}
					}
				}
			}
		}

		return array(
			'summary' => array(
				'dry_run'       => false,
				'scanned_posts' => count( $posts ),
				'media_ids'     => count( $media_ids ),
				'candidates'    => $candidates,
				'changed'       => count( $changed ),
				'failed'        => count( $failed ),
				'skipped'       => count( $skipped ),
			),
			'changed' => $changed,
			'failed'  => $failed,
			'skipped' => $skipped,
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

	private function replace_alt_text( string $image_tag, string $alt_text ): string {
		$replacement = ' alt="' . esc_attr( $alt_text ) . '"';
		$updated     = preg_replace( '/\salt\s*=\s*([\'"])(.*?)\1/i', $replacement, $image_tag, 1 );

		return is_string( $updated ) ? $updated : $image_tag;
	}

	private function replace_once( string $content, string $search, string $replacement ): string {
		$position = strpos( $content, $search );
		if ( false === $position ) {
			return $content;
		}

		return substr( $content, 0, $position ) . $replacement . substr( $content, $position + strlen( $search ) );
	}

	private function replace_block_alt_attributes( string $content, int $media_id, string $alt_text ): string {
		$updated = preg_replace_callback(
			'/<!--\s+wp:image\s+({.*?})\s+-->/s',
			static function ( array $matches ) use ( $media_id, $alt_text ): string {
				$attributes = json_decode( (string) $matches[1], true );
				if ( ! is_array( $attributes ) || absint( $attributes['id'] ?? 0 ) !== $media_id ) {
					return (string) $matches[0];
				}

				$attributes['alt'] = $alt_text;
				$encoded = json_encode( $attributes, JSON_UNESCAPED_SLASHES );
				if ( ! is_string( $encoded ) ) {
					return (string) $matches[0];
				}

				return '<!-- wp:image ' . $encoded . ' -->';
			},
			$content
		);

		return is_string( $updated ) ? $updated : $content;
	}

	/**
	 * Per-entry durability check: the intended alt for $media_id must be present
	 * on a stored img tag after the write. Document-level !== would mis-report
	 * when one of several replacements is filtered out.
	 */
	private function stored_content_has_intended_alt( string $stored_content, int $media_id, string $intended_alt ): bool {
		if ( $media_id <= 0 || '' === $intended_alt ) {
			return false;
		}

		$matches = $this->find_image_tags_for_media( $stored_content, $media_id );
		if ( 0 === count( $matches ) ) {
			return false;
		}

		foreach ( $matches as $tag ) {
			$extracted = $this->extract_alt_text( $tag );
			if ( null !== $extracted && $extracted === $intended_alt ) {
				return true;
			}
		}

		return false;
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
