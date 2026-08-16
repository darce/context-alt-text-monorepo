<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/trait-expects-meta-after-core-transforms.php';
require_once __DIR__ . '/../class-alt-text-write-status.php';

use AltContext\Api\AltTextWriteStatus;
use WP_Error;

use function absint;
use function array_slice;
use function array_values;
use function current_time;
use function delete_post_meta;
use function get_current_user_id;
use function get_post;
use function get_post_meta;
use function get_post_mime_type;
use function get_posts;
use function hash;
use function is_array;
use function is_object;
use function is_string;
use function sanitize_text_field;
use function trim;
use function update_post_meta;

class DescriptionHistoryService {
	use ExpectsMetaAfterCoreTransforms;

	private const PROVENANCE_META = '_acx_description_provenance';
	private const HUMAN_EDIT_META = '_acx_description_human_edit';
	private const PROVENANCE_PENDING_META = '_acx_description_provenance_pending';
	private const RUN_STATUS_META = '_acx_description_run_status';
	private const ALT_META = '_wp_attachment_image_alt';
	/**
	 * Durable marker that empty alt is deliberate (decorative image). Value is
	 * always the string '1' when set; deleted (never set to ''/'0') when not.
	 * Write-path only plants after a verified alt write; build_row treats its
	 * presence as reason `decorative` when alt is empty. [WBUX-5-S2C3C-BR-01]
	 */
	private const DECORATIVE_META = 'acx_alt_decorative';

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
	 * Decorative flag (WBUX-5-S2C3C-BR-01 / A-02): optional third argument is
	 * tri-state `?bool $decorative = null` so every existing two-argument caller
	 * keeps working (null ≡ today's prior default-false behaviour):
	 *   true  — mark decorative: plant after verified empty alt read-back [A-01]
	 *   false — explicit un-mark: clear the marker even when alt is empty [INT-09]
	 *   null  — unspecified: clear only when verified alt read-back is non-empty;
	 *           empty non-decorative leaves a prior marker untouched
	 * decorative=true with a non-empty pre-write alt is a 400 contradiction —
	 * never coerced. decorative=true when a sanitize filter injects a non-empty
	 * stored alt is a post-write PARTIAL (refuse to plant) — never silent plant
	 * [DATA-14]. Marker is planted only after both alt and human-edit writes are
	 * verified (not on alt-write failure or the partial-failure path). A verified
	 * non-empty alt (or explicit false) clears any prior marker immediately —
	 * before the human-edit write — so later PARTIAL returns leave disk
	 * consistent (self-healing). Clear-failure PARTIAL is deferred until after
	 * human-edit so provenance is not skipped [CO-01]. Success and PARTIAL
	 * envelopes both emit is_decorative from storage read-back [A-03][rg-015].
	 *
	 * @return array<string,mixed>|WP_Error
	 */
	public function record_correction( int $media_id, string $alt_text, ?bool $decorative = null ): array|WP_Error {
		$normalized_alt_text = sanitize_text_field( trim( $alt_text ) );

		// decorative === true means empty alt. Non-empty + decorative is
		// incoherent: reject 400, write nothing. Do not blank the alt or ignore
		// the flag — guessing which half the caller meant is [rg-015].
		// Tri-state still holds: null and false are both falsy here, so only an
		// explicit mark (true) can trip the contradiction guard [A-02].
		if ( $decorative && '' !== $normalized_alt_text ) {
			return new WP_Error(
				'description_correction_failed',
				'Cannot mark an image as decorative when alt_text is non-empty. Decorative means empty alt; send alt_text as "" or omit decorative.',
				array( 'status' => 400 )
			);
		}

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

		// S3-02 / WBUX-5-R16-BR-10 / R22-BR-03 / R23-BR-01: always read alt back
		// and compare against the shared post-transform expectation. A non-false
		// update_post_meta may still persist a divergent value — trusting the
		// return alone would report success with the wrong alt. False returns
		// (failure *and* no-op) still succeed only when storage already equals
		// the expectation.
		//
		// Expected value must mirror update_metadata() (wp-includes/meta.php):
		//   $meta_value = wp_unslash( $meta_value );
		//   $meta_value = sanitize_meta( $meta_key, $meta_value, $meta_type );
		// Unslash alone is necessary but not sufficient: a sanitize_{type}_meta_{key}
		// filter (or register_meta sanitize_callback) alters the stored form, so a
		// successful write / no-op re-save would fail the read-back and 500 a
		// write that landed (R16-BR-15). Ask sanitize_meta() what core will store
		// (see expected_meta_after_core_transforms). BR-17 (backslash re-save)
		// remains load-bearing via the unslash half.
		// [INT-11] a failed write must leave the operator path and data intact —
		// do not stamp human-edit meta unless the alt write is verified.
		$expected_alt = $this->expected_meta_after_core_transforms( self::ALT_META, $normalized_alt_text );
		update_post_meta( $media_id, self::ALT_META, $normalized_alt_text );
		$current = get_post_meta( $media_id, self::ALT_META, true );
		$alt_ok  = is_string( $current ) && $expected_alt === $current;
		if ( ! $alt_ok ) {
			// [HAI-13] surface a visible, operator-actionable failure.
			// Do not advise "try again": a durable store failure or a value
			// WP will never retain is not fixed by retrying the same write.
			return new WP_Error(
				'description_correction_failed',
				'Could not save the alt text for this media item.',
				array( 'status' => 500 )
			);
		}

		// Self-heal / un-mark decorative marker BEFORE human-edit so later
		// return paths leave disk consistent. [WBUX-5-R3-01][WBUX-5-R1-02][A-02]
		// Tri-state [INT-09]:
		//   false — explicit un-mark: clear even when alt is empty
		//   null  — unspecified: clear only when verified alt is non-empty
		//           (byte-for-byte today's prior `false` behaviour)
		//   true  — mark path; plant waits until both writes verify below
		// Reconcile from the server's own read-back ($current), never the request body.
		// $current is provably a string here: the alt_ok gate above returns when not.
		$clear_failure = null;
		if ( false === $decorative || ( null === $decorative && '' !== trim( $current ) ) ) {
			delete_post_meta( $media_id, self::DECORATIVE_META );
			// Mirror the plant path's read-back [A-04][rg-002]: a surviving
			// decorative marker is emitted as isDecorative on the next list fetch
			// (class-api.php), so claiming success while delete failed is a
			// durable-contract lie — same partial envelope the plant uses.
			$decorative_after_clear = get_post_meta( $media_id, self::DECORATIVE_META, true );
			if ( is_string( $decorative_after_clear ) && '1' === $decorative_after_clear ) {
				// Defer this PARTIAL until after the human-edit write [CO-01].
				// Returning early would leave the corrected alt on disk without a
				// human_edit provenance marker, so downstream readers treat the
				// row as machine-authored. Pre-clear ordering (this block still
				// runs before human-edit) remains load-bearing for disk
				// consistency on later returns — do not move clear after
				// human-edit to "simplify". Capture the failure, continue, then
				// prefer human-edit PARTIAL if that write also fails (strictly
				// worse: no provenance at all).
				$clear_failure = new WP_Error(
					'description_correction_partial',
					'Alt text was saved, but the decorative marker could not be cleared. Please try again so the image is treated as described.',
					array(
						'status'          => 500,
						'stored_alt_text' => is_string( $expected_alt ) ? $expected_alt : $normalized_alt_text,
						// Server-owned marker truth for client cache reconcile [A-03][rg-015][DATA-14].
						'is_decorative'   => true,
					)
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
		// What WP will actually store: unslash then sanitize_meta (same order as
		// update_metadata). Full-payload equality still required (BR-48a).
		// R23-BR-01 / R22-BR-03: always read human-edit back. A non-false accept
		// may still persist a divergent array — the return value is not verification.
		// Accept only a full-payload match: comparing only alt_text would treat a
		// stale prior marker (same text, older edited_at / different user_id) as
		// success — forging 200 while telemetry attributes the correction to the
		// wrong time/operator. Same-second re-save still passes: edited_at is
		// second-granularity and the duplicate payload is identical. [BR-48a]
		// Compare against the unslash+sanitize_meta payload (BR-17 / R16-BR-15).
		$expected_human = $this->expected_meta_after_core_transforms( self::HUMAN_EDIT_META, $human_edit_payload );
		update_post_meta( $media_id, self::HUMAN_EDIT_META, $human_edit_payload );
		$current_human = get_post_meta( $media_id, self::HUMAN_EDIT_META, true );
		$human_ok      = is_array( $current_human ) && $expected_human === $current_human;
		if ( ! $human_ok ) {
			// stored_alt_text reports what storage actually holds after
			// sanitize_text_field() + WP's unslash + sanitize_meta. Clients
			// reconcile cache from this field; without it they can only guess
			// from the request body. Only this path carries it — the
			// 404/400/alt-write-failure paths stored nothing new. [rg-015]
			// Decorative marker already self-healed above when alt was non-empty
			// or explicit un-mark ran. is_decorative is the post-write read-back
			// of acx_alt_decorative — plant never ran on this path, but a prior
			// marker may still exist (empty unspecified) or may already be
			// cleared (non-empty / explicit false) [A-03].
			// When clear also failed, human-edit PARTIAL wins: no provenance is
			// strictly worse than a surviving decorative marker [CO-01].
			return new WP_Error(
				'description_correction_partial',
				'Alt text was saved, but the human-edit record could not be stored. Please try again so history stays accurate.',
				array(
					'status'          => 500,
					'stored_alt_text' => is_string( $expected_alt ) ? $expected_alt : $normalized_alt_text,
					'is_decorative'   => $this->read_decorative_marker( $media_id ),
				)
			);
		}

		// Clear failed but human-edit landed: surface the deferred clear-failure
		// PARTIAL now (same message + data as the pre-defer arm) [CO-01].
		if ( null !== $clear_failure ) {
			return $clear_failure;
		}

		// Both writes verified: a prior provenance-gap marker is no longer an
		// unrecorded gap — the human-edit trail covers the item [R20-BR-25].
		//
		// R21-BR-10: delete is unchecked (no return / no read-back). A surviving
		// marker is tolerable here because human_edit is a verified array, so
		// build_item includes the row via human_edit regardless of the marker.
		// The zombie does not invent a pure-gap lie (provenance/human_edit null);
		// at worst it is redundant until a later successful write clears it.
		// Escalating to 500 would falsely claim the correction itself failed.
		delete_post_meta( $media_id, self::PROVENANCE_PENDING_META );

		// Decorative plant — only after both alt and human-edit are verified
		// (not on alt-write failure, not on the partial-failure path).
		// Non-empty clear already ran above (before human-edit). Empty
		// non-decorative leaves any prior marker alone. [WBUX-5-S2C3C-BR-01]
		//
		// [A-01][rg-015][DATA-14]: plant keys on the verified alt read-back
		// ($current), not the request flag alone — symmetric with the clear
		// path above. A sanitize_post_meta__wp_attachment_image_alt filter can
		// map '' → non-empty after the pre-write 400 guard (which only sees
		// $normalized_alt_text), so planting on $decorative alone can co-locate
		// acx_alt_decorative='1' with a non-empty stored alt — the exact
		// self-contradicting disk state the 400 exists to prevent.
		//
		// Decision when $decorative is true but $current is non-empty: refuse
		// to plant and return WP_Error (partial). Do not silently treat as
		// non-decorative success — that would invent a finished-contract
		// outcome from a filter-injected alt the operator never authored
		// [rg-015]. Partial (not bare failed): alt + human-edit already
		// verified; only the decorative half of the requested finish cannot
		// honestly hold. Clear any prior marker first so this path never leaves
		// acx_alt_decorative='1' beside a non-empty stored alt [DATA-14] —
		// the early clear block above skips when $decorative === true.
		//
		// S7-BR-03: read the marker back after plant. Without acx_alt_decorative,
		// empty alt is classified as missing_alt rather than decorative —
		// claiming success while the marker is absent is a durable-contract lie
		// (same pattern as ALT_META / HUMAN_EDIT_META above).
		if ( $decorative ) {
			if ( '' !== trim( $current ) ) {
				// Prior marker may still be on disk (plant path skipped the early
				// clear). Clear + read-back before returning [DATA-14].
				$marker_clear = self::clear_decorative_marker_after_verified_alt( $media_id, $current );
				if ( ! $marker_clear ) {
					return new WP_Error(
						'description_correction_partial',
						'Alt text was saved, but the decorative marker could not be cleared. Please try again so the image is treated as described.',
						array(
							'status'          => 500,
							'stored_alt_text' => $current,
							// Clear failed: marker still '1' on disk [A-03][DATA-14].
							'is_decorative'   => true,
						)
					);
				}
				return new WP_Error(
					'description_correction_partial',
					'Alt text was saved, but the stored value is non-empty so the decorative marker was not planted. Decorative requires empty alt; correct the stored alt or retry without decorative.',
					array(
						'status'          => 500,
						'stored_alt_text' => $current,
						// Marker clear verified; is_decorative from storage read-back [A-03].
						'is_decorative'   => $this->read_decorative_marker( $media_id ),
					)
				);
			}
			update_post_meta( $media_id, self::DECORATIVE_META, '1' );
			$decorative_current = get_post_meta( $media_id, self::DECORATIVE_META, true );
			$decorative_ok      = is_string( $decorative_current ) && '1' === $decorative_current;
			if ( ! $decorative_ok ) {
				// Alt + human-edit already verified; marker did not land. Partial
				// code (not bare failed): empty alt is in storage, only the
				// durable decorative half of the finish is missing.
				return new WP_Error(
					'description_correction_partial',
					'Alt text was saved, but the decorative marker could not be stored. Please try again so the image is treated as decorative.',
					array(
						'status'          => 500,
						'stored_alt_text' => is_string( $expected_alt ) ? $expected_alt : $normalized_alt_text,
						// Plant failed: marker is absent (or not '1') [A-03].
						'is_decorative'   => false,
					)
				);
			}
		}

		// After a verified human-edit write (or accepted full-payload no-op),
		// storage holds an array under HUMAN_EDIT_META. build_item is therefore
		// total for this media_id: it only returns null when media_id <= 0
		// (ruled out by attachment validation above) or when none of provenance,
		// human_edit, or (pending marker + non-empty alt) qualifies. No legitimate
		// input reaches null here under WP storage or the test stubs. [BR-55]
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
	 * Build one history row, or null when this attachment is outside history.
	 *
	 * Inclusion is narrow and evidence-based (WBUX-5-R16-BR-06):
	 * - provenance array (this system stamped an audit trail), or
	 * - human_edit array (operator correction path), or
	 * - durable `_acx_description_provenance_pending` with non-empty string
	 *   `run_id` + `draft_hash` **and** non-empty current alt (alt landed;
	 *   provenance write failed — bulk apply and single-image write plant this
	 *   marker only after verified write). Empty / partial-shape arrays are
	 *   not recovery evidence [R20-BR-21].
	 *
	 * Do not widen to "any non-empty alt": that lists every human-authored media
	 * library row this plugin never touched. Gap rows keep an honest envelope
	 * (`provenance`/`human_edit` null, `generated_alt_text` '') — fabricate nothing.
	 *
	 * @return array<string,mixed>|null
	 */
	protected function build_item( int $media_id ): ?array {
		if ( $media_id <= 0 ) {
			return null;
		}

		$provenance  = get_post_meta( $media_id, self::PROVENANCE_META, true );
		$human_edit  = get_post_meta( $media_id, self::HUMAN_EDIT_META, true );
		$pending     = get_post_meta( $media_id, self::PROVENANCE_PENDING_META, true );
		$current_alt = (string) get_post_meta( $media_id, self::ALT_META, true );
		// Provenance-gap partial: durable marker shape (run_id + draft_hash) + alt
		// present. Empty / partial arrays carry no recovery info [R20-BR-21].
		$provenance_gap = self::is_verified_pending_marker( $pending ) && '' !== trim( $current_alt );

		if ( ! is_array( $provenance ) && ! is_array( $human_edit ) && ! $provenance_gap ) {
			return null;
		}

		$post       = get_post( $media_id );
		$run_status = get_post_meta( $media_id, self::RUN_STATUS_META, true );
		// is_decorative is server-owned storage truth (boolean, not the raw
		// '1'/'' meta string). The correction success envelope is build_item;
		// clients must not re-derive this from request intent [A-03][rg-015].
		$is_decorative = $this->read_decorative_marker( $media_id );

		return array(
			'media_id'           => $media_id,
			'title'              => is_object( $post ) && isset( $post->post_title ) ? (string) $post->post_title : '',
			'mime_type'          => (string) get_post_mime_type( $media_id ),
			'current_alt_text'   => $current_alt,
			'generated_alt_text' => $this->resolve_generated_alt_text( is_array( $provenance ) ? $provenance : array() ),
			'provenance'         => is_array( $provenance ) ? $provenance : null,
			'human_edit'         => is_array( $human_edit ) ? $human_edit : null,
			'run_status'         => is_array( $run_status ) ? $run_status : null,
			'is_decorative'      => $is_decorative,
		);
	}

	/**
	 * Whether acx_alt_decorative is currently planted for this attachment.
	 *
	 * Casts the durable '1' string meta to a real boolean for wire envelopes.
	 * Read-back only — never invents a value from request intent [A-03][rg-015].
	 */
	private function read_decorative_marker( int $media_id ): bool {
		$raw = get_post_meta( $media_id, self::DECORATIVE_META, true );
		return is_string( $raw ) && '1' === $raw;
	}

	/**
	 * Clear acx_alt_decorative after a verified non-empty alt write.
	 *
	 * Shared by alt writers that are not the correction plant path (REST
	 * single-image describe, CLI generate, and adoptable by bulk apply). Call
	 * only after alt write read-back succeeded — never on an unverified write.
	 * Empty verified alt is a no-op (marker may legitimately remain). Returns
	 * whether the marker is clear afterwards: true when absent / not '1', or
	 * when alt was empty; false only when delete ran and the marker still
	 * reads '1' [DATA-14].
	 *
	 * @param int    $media_id      Attachment ID.
	 * @param string $verified_alt  Post-write alt read-back (already verified).
	 */
	public static function clear_decorative_marker_after_verified_alt( int $media_id, string $verified_alt ): bool {
		if ( '' === trim( $verified_alt ) ) {
			return true;
		}
		delete_post_meta( $media_id, self::DECORATIVE_META );
		// [DATA-14] delete_post_meta return is not verification.
		$after = get_post_meta( $media_id, self::DECORATIVE_META, true );
		return ! ( is_string( $after ) && '1' === $after );
	}

	/**
	 * Whether stored pending meta is a usable recovery marker.
	 *
	 * Writers always plant `{ run_id: non-empty string, draft_hash: non-empty
	 * string }`. Array-ness alone is not enough — `[]` and partial shapes carry
	 * no recovery information [R20-BR-21].
	 *
	 * Public + static so writers (single-image, CLI, bulk apply) share this
	 * exact shape predicate with the history reader — no writer/reader drift
	 * [R21-BR-08]. Empty / whitespace-only strings are rejected (trim).
	 *
	 * @param mixed $pending Raw post meta value.
	 */
	public static function is_verified_pending_marker( mixed $pending ): bool {
		if ( ! is_array( $pending ) ) {
			return false;
		}
		$run_id     = $pending['run_id'] ?? null;
		$draft_hash = $pending['draft_hash'] ?? null;
		return is_string( $run_id )
			&& '' !== trim( $run_id )
			&& is_string( $draft_hash )
			&& '' !== trim( $draft_hash );
	}

	/**
	 * Canonical marker `draft_hash` domain: sha256 of the **stored** alt form
	 * (what WordPress persists after wp_unslash + sanitize_meta), never the raw
	 * pre-transform draft. All plant sites and both recovery predicates must use
	 * this helper so a future writer cannot hash the wrong domain [R22-BR-01].
	 */
	public static function hash_for_stored_alt( string $stored_alt ): string {
		return hash( 'sha256', $stored_alt );
	}

	/**
	 * Live recovery marker for a stored alt: verified shape and draft_hash
	 * equals sha256( stored alt ). skip_existing must not wipe these — the gap
	 * remains real and is the only durable recovery evidence [R21-BR-01]
	 * [R22-BR-01]. run_id is not compared — liveness is content-scoped.
	 * For "is *this run's* marker dead evidence?" use
	 * {@see self::is_stale_own_run_marker_for_alt()} [R23-BR-19].
	 *
	 * @param mixed $pending Raw post meta value.
	 */
	public static function is_live_recovery_marker_for_alt( mixed $pending, string $stored_alt ): bool {
		if ( ! self::is_verified_pending_marker( $pending ) ) {
			return false;
		}
		if ( '' === trim( $stored_alt ) ) {
			return false;
		}
		// $pending is verified-shape array here; draft_hash is a non-empty string.
		/** @var array{run_id: string, draft_hash: string} $pending */
		return self::hash_for_stored_alt( $stored_alt ) === (string) $pending['draft_hash'];
	}

	/**
	 * Whether `$pending` is dead recovery evidence *for a specific run*.
	 *
	 * Staleness is not a free-floating property of whatever the marker last
	 * held [R23-BR-19]: both legs are required —
	 *   1. Identity: marker.run_id === $run_id (this run owns the slot)
	 *   2. Content:  draft_hash is not live for $stored_alt
	 *              ({@see self::is_live_recovery_marker_for_alt()})
	 *
	 * A foreign marker's draft_hash must never decide whether *this* run's
	 * marker is stale (two runs would be indistinguishable by content alone).
	 * Returns false when the marker is foreign, unverified, or still live for
	 * the stored alt — callers must not delete on a false result alone when
	 * they also need the prov_is_this_run cleanup path.
	 *
	 * @param mixed  $pending    Raw post meta value.
	 * @param string $stored_alt Currently stored alt (string branch).
	 * @param string $run_id     Applying / judged run id.
	 */
	public static function is_stale_own_run_marker_for_alt( mixed $pending, string $stored_alt, string $run_id ): bool {
		if ( ! self::is_verified_pending_marker( $pending ) ) {
			return false;
		}
		// Identity leg: only this run's marker is eligible for own-run cleanup.
		/** @var array{run_id: string, draft_hash: string} $pending */
		if ( (string) $pending['run_id'] !== $run_id ) {
			return false;
		}
		// Content leg: draft_hash no longer matches the stored alt.
		return ! self::is_live_recovery_marker_for_alt( $pending, $stored_alt );
	}

	/**
	 * Empty recovery descriptor: first write / overwrite (no recovery) [R23-BR-22].
	 *
	 * Always-present shape — never omit `recovered_from` from a bulk envelope.
	 *
	 * @return array{origin: null, kind: string, chain: list<string>}
	 */
	public static function empty_recovered_from(): array {
		return array(
			'origin' => null,
			'kind'   => AltTextWriteStatus::RECOVERY_KIND_NONE,
			'chain'  => array(),
		);
	}

	/**
	 * Resolve recovery `kind` for a marker owner string [R23-BR-21] [sr-007].
	 *
	 * Consults {@see AltTextWriteStatus::MARKER_OWNERS} first.
	 * UUID-shaped owners are bulk runs. Anything else is unknown — never
	 * silently typed as a run.
	 */
	public static function resolve_recovery_kind_for_owner( string $owner ): string {
		if ( in_array( $owner, AltTextWriteStatus::MARKER_OWNERS, true ) ) {
			return AltTextWriteStatus::RECOVERY_KIND_SURFACE;
		}
		if ( self::is_run_uuid_shaped( $owner ) ) {
			return AltTextWriteStatus::RECOVERY_KIND_RUN;
		}
		return AltTextWriteStatus::RECOVERY_KIND_UNKNOWN;
	}

	/**
	 * Whether `$value` looks like a bulk describe-run UUID (8-4-4-4-12 hex).
	 * Used only to discriminate kind; not an existence check.
	 */
	public static function is_run_uuid_shaped( string $value ): bool {
		return 1 === preg_match(
			'/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i',
			$value
		);
	}

	/**
	 * Normalize a prior `recovered_from` / marker chain to an oldest-first list
	 * of non-empty string origins.
	 *
	 * @param mixed $chain Raw chain list (or null).
	 *
	 * @return list<string>
	 */
	public static function normalize_recovery_chain( mixed $chain ): array {
		if ( ! is_array( $chain ) ) {
			return array();
		}
		$out = array();
		foreach ( $chain as $entry ) {
			if ( ! is_string( $entry ) ) {
				continue;
			}
			$trimmed = trim( $entry );
			if ( '' === $trimmed ) {
				continue;
			}
			$out[] = $trimmed;
		}
		return $out;
	}

	/**
	 * Append-only chain merge: prior chain, then origin if not already last.
	 *
	 * @param list<string> $chain
	 * @param string       $origin
	 *
	 * @return list<string>
	 */
	public static function append_recovery_origin( array $chain, string $origin ): array {
		$origin = trim( $origin );
		if ( '' === $origin ) {
			return $chain;
		}
		$last = $chain === array() ? null : $chain[ count( $chain ) - 1 ];
		if ( $last !== $origin ) {
			$chain[] = $origin;
		}
		return $chain;
	}

	/**
	 * Canonical recovery descriptor for non-clobber completion [R23-BR-24]
	 * [R23-BR-20] [R23-BR-21] [R23-BR-22] [R23-BR-08].
	 *
	 * Always returns the full `{ origin, kind, chain }` shape — never null and
	 * never omits keys. Callers stamp this as `recovered_from` on every bulk
	 * envelope (including first write via {@see self::empty_recovered_from()}).
	 *
	 *   - verified foreign owner → origin = marker owner, kind resolved via
	 *     MARKER_OWNERS / uuid shape, chain = prior ∪ marker chain ∪ origin
	 *   - same-run owner         → origin null, kind same_run, prior chain kept
	 *   - unverified / empty     → empty descriptor (kind none), prior chain kept
	 *     only when a prior envelope already established one (passthrough)
	 *
	 * `$prior_recovered_from` is a previous envelope's `recovered_from` (or null).
	 * Its chain is carried forward so consecutive provenance-write failures do
	 * not drop the true originator [R23-BR-20].
	 *
	 * One definition for every call site (bulk apply stamp, history readers).
	 * Takeover must not silently re-attribute the write to the applying run alone.
	 *
	 * @param mixed                     $pending               Raw pending marker.
	 * @param string                    $applying_run_id       Run performing recovery.
	 * @param array<string,mixed>|null  $prior_recovered_from  Prior envelope descriptor.
	 *
	 * @return array{origin: string|null, kind: string, chain: list<string>}
	 */
	public static function resolve_recovery_descriptor( mixed $pending, string $applying_run_id, ?array $prior_recovered_from = null ): array {
		$prior_chain = array();
		if ( is_array( $prior_recovered_from ) ) {
			$prior_chain = self::normalize_recovery_chain( $prior_recovered_from['chain'] ?? null );
			// If prior had an origin not yet in chain, seed it (defensive).
			$prior_origin = $prior_recovered_from['origin'] ?? null;
			if ( is_string( $prior_origin ) && '' !== trim( $prior_origin ) ) {
				$prior_chain = self::append_recovery_origin( $prior_chain, trim( $prior_origin ) );
			}
		}

		// Marker may itself carry a chain from a re-plant that preserved origin.
		$marker_chain = array();
		if ( is_array( $pending ) && isset( $pending['chain'] ) ) {
			$marker_chain = self::normalize_recovery_chain( $pending['chain'] );
		}
		$base_chain = $prior_chain;
		foreach ( $marker_chain as $entry ) {
			$base_chain = self::append_recovery_origin( $base_chain, $entry );
		}

		if ( ! self::is_verified_pending_marker( $pending ) ) {
			if ( array() === $base_chain ) {
				return self::empty_recovered_from();
			}
			// Prior chain without a live marker: keep chain, no new origin.
			return array(
				'origin' => null,
				'kind'   => AltTextWriteStatus::RECOVERY_KIND_NONE,
				'chain'  => $base_chain,
			);
		}

		/** @var array{run_id: string, draft_hash: string} $pending */
		$owner = trim( (string) $pending['run_id'] );
		if ( '' === $owner ) {
			return array() === $base_chain
				? self::empty_recovered_from()
				: array(
					'origin' => null,
					'kind'   => AltTextWriteStatus::RECOVERY_KIND_NONE,
					'chain'  => $base_chain,
				);
		}

		if ( $owner === $applying_run_id ) {
			return array(
				'origin' => null,
				'kind'   => AltTextWriteStatus::RECOVERY_KIND_SAME_RUN,
				'chain'  => $base_chain,
			);
		}

		$kind  = self::resolve_recovery_kind_for_owner( $owner );
		$chain = self::append_recovery_origin( $base_chain, $owner );

		return array(
			'origin' => $owner,
			'kind'   => $kind,
			'chain'  => $chain,
		);
	}

	/**
	 * Usable recovery evidence for a draft about to be (or just) written:
	 * verified shape and draft_hash matches sha256( $expected_stored_alt ),
	 * where $expected_stored_alt is the post-transform form WP will / did
	 * persist (wp_unslash + sanitize_meta) — never the raw pre-transform draft
	 * [R22-BR-01]. run_id is intentionally ignored: ownership is irrelevant to
	 * whether the alt for this draft landed; writers accept a pre-existing bulk
	 * / cross-surface marker for the same stored draft rather than demanding
	 * strict identity with the marker this path tried to plant
	 * [R21-BR-08] [R21-BR-17 key-order] [R22-BR-02].
	 * Attribution of *which* run started the write is a separate question —
	 * {@see self::resolve_recovery_descriptor()} [R23-BR-24].
	 *
	 * @param mixed  $pending              Raw post meta value.
	 * @param string $expected_stored_alt  Post-transform alt (stored domain).
	 */
	public static function is_usable_pending_marker_for_draft( mixed $pending, string $expected_stored_alt ): bool {
		if ( ! self::is_verified_pending_marker( $pending ) ) {
			return false;
		}
		/** @var array{run_id: string, draft_hash: string} $pending */
		return self::hash_for_stored_alt( $expected_stored_alt ) === (string) $pending['draft_hash'];
	}

	/**
	 * Resolve the Generated-alt column value from a provenance envelope.
	 *
	 * Preference order (product claim, BR-123): `alt_text_draft` first — the
	 * key every current writer stamps (REST single-image, CLI, bulk apply) —
	 * then legacy fallbacks. Empty after trim is treated as absent so a later
	 * key can still supply a value; both "no draft key" and "recorded empty
	 * draft" therefore surface as `''` today (BR-109). Distinguishing those
	 * would change the REST shape consumed by DescriptionHistoryPage — see
	 * REPORT.md; write-side BR-104 prevents new empty drafts from landing.
	 *
	 * Legacy keys `generated_alt_text` and `alt_text` (BR-118): no writer under
	 * `src/` currently emits either into `_acx_description_provenance` (all
	 * three paths stamp `alt_text_draft` only; provenance is replaced, not
	 * merged). Origin of the fallbacks is not established in-repo — retained
	 * as defensive readers for any pre-plugin or external envelopes, not as
	 * live product paths. Do not reorder without updating
	 * DescriptionHistoryServiceTest preference coverage.
	 *
	 * @param array<string,mixed> $provenance
	 */
	private function resolve_generated_alt_text( array $provenance ): string {
		// Order is load-bearing: alt_text_draft wins over legacy keys (BR-123).
		foreach ( array( 'alt_text_draft', 'generated_alt_text', 'alt_text' ) as $key ) {
			if ( isset( $provenance[ $key ] ) && '' !== trim( (string) $provenance[ $key ] ) ) {
				return (string) $provenance[ $key ];
			}
		}

		return '';
	}
}
