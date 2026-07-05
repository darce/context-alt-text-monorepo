<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function absint;
use function array_slice;
use function array_values;
use function current_time;
use function get_current_user_id;
use function get_post;
use function get_post_meta;
use function get_post_mime_type;
use function get_posts;
use function is_array;
use function is_object;
use function sanitize_text_field;
use function trim;
use function update_post_meta;

class DescriptionHistoryService {
	private const PROVENANCE_META = '_acx_description_provenance';
	private const HUMAN_EDIT_META = '_acx_description_human_edit';
	private const RUN_STATUS_META = '_acx_description_run_status';
	private const ALT_META = '_wp_attachment_image_alt';

	/**
	 * @return array<string,mixed>
	 */
	public function list_history( int $limit = 50, int $offset = 0 ): array {
		$ids = get_posts(
			array(
				'post_type'      => 'attachment',
				'post_status'    => 'inherit',
				'post_mime_type' => 'image',
				'fields'         => 'ids',
				'posts_per_page' => -1,
				'orderby'        => 'ID',
				'order'          => 'DESC',
			)
		);

		if ( ! is_array( $ids ) ) {
			$ids = array();
		}

		$items = array();
		foreach ( $ids as $id ) {
			$item = $this->build_item( absint( $id ) );
			if ( null !== $item ) {
				$items[] = $item;
			}
		}

		$total = count( $items );
		$items = array_values( array_slice( $items, max( 0, $offset ), max( 1, $limit ) ) );

		return array(
			'total' => $total,
			'items' => $items,
		);
	}

	/**
	 * @return array<string,mixed>
	 */
	public function record_correction( int $media_id, string $alt_text ): array {
		$normalized_alt_text = sanitize_text_field( trim( $alt_text ) );
		update_post_meta( $media_id, self::ALT_META, $normalized_alt_text );
		update_post_meta(
			$media_id,
			self::HUMAN_EDIT_META,
			array(
				'alt_text'  => $normalized_alt_text,
				'edited_at' => current_time( 'mysql' ),
				'user_id'   => get_current_user_id(),
			)
		);

		return $this->build_item( $media_id ) ?? array(
			'media_id'         => $media_id,
			'current_alt_text' => $normalized_alt_text,
		);
	}

	/**
	 * @return array<string,mixed>|null
	 */
	private function build_item( int $media_id ): ?array {
		if ( $media_id <= 0 ) {
			return null;
		}

		$provenance = get_post_meta( $media_id, self::PROVENANCE_META, true );
		$human_edit = get_post_meta( $media_id, self::HUMAN_EDIT_META, true );
		if ( ! is_array( $provenance ) && ! is_array( $human_edit ) ) {
			return null;
		}

		$post = get_post( $media_id );
		$run_status = get_post_meta( $media_id, self::RUN_STATUS_META, true );

		return array(
			'media_id'            => $media_id,
			'title'               => is_object( $post ) && isset( $post->post_title ) ? (string) $post->post_title : '',
			'mime_type'           => (string) get_post_mime_type( $media_id ),
			'current_alt_text'    => (string) get_post_meta( $media_id, self::ALT_META, true ),
			'generated_alt_text'  => $this->resolve_generated_alt_text( is_array( $provenance ) ? $provenance : array() ),
			'provenance'          => is_array( $provenance ) ? $provenance : null,
			'human_edit'          => is_array( $human_edit ) ? $human_edit : null,
			'run_status'          => is_array( $run_status ) ? $run_status : null,
		);
	}

	/**
	 * @param array<string,mixed> $provenance
	 */
	private function resolve_generated_alt_text( array $provenance ): string {
		foreach ( array( 'alt_text_draft', 'generated_alt_text', 'alt_text' ) as $key ) {
			if ( isset( $provenance[ $key ] ) && '' !== trim( (string) $provenance[ $key ] ) ) {
				return (string) $provenance[ $key ];
			}
		}

		return '';
	}
}
