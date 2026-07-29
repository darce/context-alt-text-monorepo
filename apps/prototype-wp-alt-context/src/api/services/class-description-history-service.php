<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use WP_Error;

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
use function is_string;
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
	 * Persist an operator alt-text correction.
	 *
	 * Contract (BR-40 / BR-41 / BR-55): both the alt write and the human-edit
	 * telemetry write are failure-worthy. A verified alt with a failed
	 * human-edit write returns 500 with code description_correction_partial
	 * (alt landed; telemetry did not) and data.stored_alt_text carrying the
	 * normalized value actually in storage, so clients reconcile cache from the
	 * server's truth rather than the request body. A bare alt-write failure keeps
	 * description_correction_failed and no stored_alt_text. The alt is left
	 * in place on partial failure (not rolled back) — the operator can retry;
	 * the no-op alt path already treats a re-save of the same text as success,
	 * so a retry can complete the human-edit marker.
	 *
	 * Success always returns the full history-item envelope from build_item
	 * (never a hand-built partial). After verified human-edit write, build_item
	 * is total; a null result is treated as an invariant violation (500), not a
	 * silent success fallback. [rg-015] [RLSE-05] [BR-55]
	 *
	 * @return array<string,mixed>|WP_Error
	 */
	public function record_correction( int $media_id, string $alt_text ): array|WP_Error {
		$normalized_alt_text = sanitize_text_field( trim( $alt_text ) );

		// Validate attachment identity before any write. Mirrors S3-01 in
		// DescribeController::apply_describe_run_drafts — refuse to stamp alt
		// text onto a nonexistent ID or a non-attachment post.
		$post = get_post( $media_id );
		if ( ! is_object( $post ) ) {
			return new WP_Error(
				'description_correction_failed',
				'Media item not found.',
				array( 'status' => 404 )
			);
		}
		if ( 'attachment' !== (string) ( $post->post_type ?? '' ) ) {
			return new WP_Error(
				'description_correction_failed',
				'Media item is not an attachment.',
				array( 'status' => 400 )
			);
		}

		// S3-02: honor the update_post_meta() return. It also returns false when
		// the stored value is byte-identical to $normalized_alt_text (a no-op
		// overwrite); distinguish that from a real failure via a read-back so an
		// unchanged value still counts as success rather than a false error.
		// [INT-11] a failed write must leave the operator path and data intact —
		// do not stamp human-edit meta unless the alt write is verified.
		$alt_written = update_post_meta( $media_id, self::ALT_META, $normalized_alt_text );
		if ( false === $alt_written ) {
			$current = get_post_meta( $media_id, self::ALT_META, true );
			if ( ! is_string( $current ) || $normalized_alt_text !== $current ) {
				// [HAI-13] surface a visible, operator-actionable failure.
				return new WP_Error(
					'description_correction_failed',
					'Could not save the alt text for this media item. Please try again.',
					array( 'status' => 500 )
				);
			}
		}

		// Human-edit meta is required for an honest correction response and for
		// list_history parity. Failure after a verified alt is still an error
		// (BR-40 option a): do not claim success when stored telemetry lags.
		// Alt text is intentionally left written — retry completes the marker.
		//
		// Code is description_correction_partial (literal, not derived): the alt
		// write is verified, so the operator's text landed. Clients must be able
		// to distinguish this from a bare alt-write failure. [rg-015]
		$human_edit_payload = array(
			'alt_text'  => $normalized_alt_text,
			'edited_at' => current_time( 'mysql' ),
			'user_id'   => get_current_user_id(),
		);
		$human_written = update_post_meta( $media_id, self::HUMAN_EDIT_META, $human_edit_payload );
		if ( false === $human_written ) {
			$current_human = get_post_meta( $media_id, self::HUMAN_EDIT_META, true );
			// Accept only a full-payload no-op: update_post_meta returns false when
			// the stored value equals the value being written (the whole array).
			// Comparing only alt_text would treat a stale prior marker (same text,
			// older edited_at / different user_id) as success — forging 200 while
			// telemetry attributes the correction to the wrong time/operator.
			// Same-second re-save still passes: edited_at is second-granularity and
			// the duplicate payload is identical. [BR-48a]
			$human_ok = is_array( $current_human ) && $human_edit_payload === $current_human;
			if ( ! $human_ok ) {
				// stored_alt_text reports what storage actually holds after
				// sanitize_text_field(). Clients reconcile their cache from this
				// field; without it they can only guess from the request body and
				// would display markup/whitespace that was stripped. Only this path
				// carries it — the 404/400/alt-write-failure paths stored nothing
				// new, so there is nothing honest to report. [rg-015]
				return new WP_Error(
					'description_correction_partial',
					'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.',
					array(
						'status'          => 500,
						'stored_alt_text' => $normalized_alt_text,
					)
				);
			}
		}

		// After a verified human-edit write (or accepted full-payload no-op),
		// storage holds an array under HUMAN_EDIT_META. build_item is therefore
		// total for this media_id: it only returns null when media_id <= 0
		// (ruled out by attachment validation above) or when neither provenance
		// nor human_edit is an array. No legitimate input reaches null here under
		// WP storage or the test stubs. [BR-55]
		//
		// A silent success envelope on that unreachable state would be [RLSE-05]
		// (the shape BR-40 removed). Surface an explicit 500 instead of fabricating
		// a hand-built item. [rg-015]
		$item = $this->build_item( $media_id );
		if ( null === $item ) {
			return new WP_Error(
				'description_correction_failed',
				'The correction was stored, but the history item could not be loaded. Please reload the page to confirm.',
				array( 'status' => 500 )
			);
		}

		return $item;
	}

	/**
	 * @return array<string,mixed>|null
	 */
	protected function build_item( int $media_id ): ?array {
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
