<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

require_once __DIR__ . '/trait-maps-response-fields.php';

use AltContext\Support\Telemetry;
use function absint;
use function array_slice;
use function array_values;
use function is_array;
use function is_numeric;
use function is_string;
use function trim;

class ClusterResponseMapper {
	use MapsResponseFields;

	/**
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @param array<string,array<int,array<string,mixed>>> $members_by_cluster
	 * @param int|null $preview_limit Per-cluster member fetch cap; when set, members were
	 *                                fetched for this page (densify sparse maps) and counts
	 *                                at exactly this cap are expected truncation, not drift.
	 * @return array<int,array<string,mixed>>
	 */
	public function map_cluster_list( array $cluster_rows, array $members_by_cluster, ?int $preview_limit = null ): array {
		if ( null !== $preview_limit ) {
			$members_by_cluster = $this->densify_members_for_cluster_rows( $cluster_rows, $members_by_cluster );
		}

		$results = array();

		foreach ( $cluster_rows as $row ) {
			$cluster_id = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			$members    = array();
			if ( '' !== $cluster_id && isset( $members_by_cluster[ $cluster_id ] ) && is_array( $members_by_cluster[ $cluster_id ] ) ) {
				$members = $members_by_cluster[ $cluster_id ];
			}
			$results[] = $this->map_cluster_summary( $row, $members, isset( $members_by_cluster[ $cluster_id ] ), $preview_limit );
		}

		return $results;
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 * @param array<int,array<string,mixed>> $member_rows
	 * @param int|null $preview_limit Optional per-cluster fetch cap (see map_cluster_list).
	 * @return array<string,mixed>
	 */
	public function map_cluster_detail( array $cluster_row, array $member_rows, ?int $preview_limit = null ): array {
		return $this->map_cluster_summary( $cluster_row, $member_rows, true, $preview_limit );
	}

	/**
	 * @param array<int,string> $labels
	 * @return array<int,string>
	 */
	public function map_labels_list( array $labels ): array {
		$normalized = array();
		foreach ( $labels as $label ) {
			$value = trim( (string) $label );
			if ( '' !== $value ) {
				$normalized[] = $value;
			}
		}

		return $normalized;
	}

	/**
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @param array<string,array<int,array<string,mixed>>> $members_by_cluster
	 * @param string $tenant_id
	 * @param int|null $preview_limit Per-cluster member fetch cap (see map_cluster_list).
	 * @return array<int,array<string,mixed>>
	 */
	public function map_top_unlabeled_clusters( array $cluster_rows, array $members_by_cluster, string $tenant_id, ?int $preview_limit = null ): array {
		if ( null !== $preview_limit ) {
			$members_by_cluster = $this->densify_members_for_cluster_rows( $cluster_rows, $members_by_cluster );
		}

		$results = array();

		foreach ( $cluster_rows as $row ) {
			$cluster_id = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_id ) {
				continue;
			}

			$members = array();
			if ( isset( $members_by_cluster[ $cluster_id ] ) && is_array( $members_by_cluster[ $cluster_id ] ) ) {
				$members = $members_by_cluster[ $cluster_id ];
			}

			$representatives = array();
			foreach ( array_slice( $members, 0, 4 ) as $member_row ) {
				$representatives[] = $this->map_top_unlabeled_representative( $row, $member_row );
			}

			$label_state = $this->resolve_label_state( $row );

			$results[] = array(
				'id' => $cluster_id,
				'tenant_id' => $tenant_id,
				'label' => $label_state['label'],
				'is_labeled' => $label_state['is_labeled'],
				'is_auto_label' => $label_state['is_auto_label'],
				'identity_count' => $this->resolve_identity_count( $row, $members, isset( $members_by_cluster[ $cluster_id ] ), $preview_limit ),
				'user_confirmed' => $label_state['user_confirmed'],
				'suggested_label' => isset( $row['suggested_label'] ) && '' !== $row['suggested_label'] ? (string) $row['suggested_label'] : null,
				'suggested_label_source' => isset( $row['suggested_label_source'] ) && '' !== $row['suggested_label_source'] ? (string) $row['suggested_label_source'] : null,
				'suggested_label_confidence' => isset( $row['suggested_label_confidence'] ) && '' !== $row['suggested_label_confidence'] ? (float) $row['suggested_label_confidence'] : null,
				'suggested_target_cluster_id' => isset( $row['suggested_target_cluster_id'] ) && '' !== $row['suggested_target_cluster_id'] ? (string) $row['suggested_target_cluster_id'] : null,
				'representatives' => $representatives,
			);
		}

		return $results;
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 * @param array<int,array<string,mixed>> $member_rows
	 * @param int|null $preview_limit
	 * @return array<string,mixed>
	 */
	private function map_cluster_summary( array $cluster_row, array $member_rows, bool $members_loaded, ?int $preview_limit = null ): array {
		$cluster_id = trim( (string) ( $cluster_row['cluster_uuid'] ?? '' ) );
		$label_state = $this->resolve_label_state( $cluster_row );
		$members    = array_values( $member_rows );

		$sample_members = array_slice( $members, 0, 4 );
		$member_ids     = array();
		foreach ( $members as $member_row ) {
			$member_id = trim( (string) ( $member_row['identity_uuid'] ?? '' ) );
			if ( '' !== $member_id ) {
				$member_ids[] = $member_id;
			}
		}

		$representative = $this->map_representative_identity( $cluster_row, $sample_members );

		$sample_identities = array();
		foreach ( $sample_members as $member_row ) {
			$sample_identities[] = $this->map_cluster_identity( $member_row );
		}

		$person_uuid = trim( (string) ( $cluster_row['person_uuid'] ?? '' ) );

		return array(
			'id' => $cluster_id,
			'label' => $label_state['label'],
			'is_auto_label' => $label_state['is_auto_label'],
			'identity_count' => $this->resolve_identity_count( $cluster_row, $members, $members_loaded, $preview_limit ),
			'member_ids' => $member_ids,
			'representative_identity' => $representative,
			'sample_identities' => $sample_identities,
			'person_uuid' => '' !== $person_uuid ? $person_uuid : null,
		);
	}

	/**
	 * @param array<string,mixed> $member_row
	 * @return array<string,mixed>
	 */
	private function map_cluster_identity( array $member_row ): array {
		$media_id = absint( $member_row['attachment_id'] ?? $member_row['media_id'] ?? 0 );
		$bbox     = $this->extract_bbox_pixels( $member_row['bbox_json'] ?? null );

		return array(
			'identity_id' => trim( (string) ( $member_row['identity_uuid'] ?? '' ) ),
			'media_id' => $media_id,
			'similarity' => $this->normalize_similarity_value( $member_row ),
			'confidence' => $this->normalize_confidence_value( $member_row ),
			'clustering_pending' => false,
			'bbox' => $bbox,
			'thumb_url' => $this->resolve_thumb_url( $member_row, $media_id ),
			'attachment_url' => $this->resolve_media_url( $media_id ),
			'media_url' => $this->resolve_media_url( $media_id ),
			'is_pinned' => $this->normalize_boolean_value( $member_row['is_pinned'] ?? false ),
		);
	}

	/**
	 * @param array<string,mixed> $member_row
	 * @return array<string,mixed>
	 */
	private function map_top_unlabeled_representative( array $cluster_row, array $member_row ): array {
		$media_id = absint( $member_row['attachment_id'] ?? $member_row['media_id'] ?? 0 );
		$representative_id = trim( (string) ( $cluster_row['representative_id'] ?? '' ) );
		$member_identity_id = trim( (string) ( $member_row['identity_uuid'] ?? '' ) );
		$is_pinned = $this->normalize_boolean_value( $member_row['is_pinned'] ?? false );
		if ( ! $is_pinned && '' !== $representative_id && $representative_id === $member_identity_id ) {
			$is_pinned = $this->normalize_boolean_value( $cluster_row['is_pinned'] ?? false );
		}

		return array(
			'id' => $member_identity_id,
			'media_id' => $media_id,
			'thumb_url' => $this->resolve_thumb_url( $member_row, $media_id ),
			'attachment_url' => $this->resolve_media_url( $media_id ),
			'media_url' => $this->resolve_media_url( $media_id ),
			'bbox' => $this->extract_bbox_pixels( $member_row['bbox_json'] ?? null ),
			'is_pinned' => $is_pinned,
		);
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 * @param array<int,array<string,mixed>> $member_rows
	 * @return array<string,mixed>
	 */
	private function map_representative_identity( array $cluster_row, array $member_rows ): array {
		$representative      = $member_rows[0] ?? array();
		$media_id            = absint( $representative['attachment_id'] ?? $representative['media_id'] ?? 0 );
		$bbox                = $this->extract_bbox_pixels( $representative['bbox_json'] ?? null );
		$representative_id   = trim( (string) ( $cluster_row['representative_id'] ?? '' ) );
		$member_identity_id  = trim( (string) ( $representative['identity_uuid'] ?? '' ) );
		$is_pinned           = $this->normalize_boolean_value( $representative['is_pinned'] ?? false );

		$thumb_media_id = $this->extract_media_id_from_thumb_path( $cluster_row['representative_thumb_path'] ?? '' );
		if ( $media_id <= 0 && $thumb_media_id > 0 ) {
			$media_id = $thumb_media_id;
		}
		if ( ! $is_pinned && ( array() === $representative || ( '' !== $representative_id && $representative_id === $member_identity_id ) ) ) {
			$is_pinned = $this->normalize_boolean_value( $cluster_row['is_pinned'] ?? false );
		}

		return array(
			'media_id' => $media_id > 0 ? $media_id : null,
			'bbox' => $bbox,
			'is_pinned' => $is_pinned,
		);
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 * @param array<int,array<string,mixed>> $member_rows
	 * @param int|null $preview_limit
	 */
	private function resolve_identity_count( array $cluster_row, array $member_rows, bool $members_loaded, ?int $preview_limit = null ): int {
		if ( is_numeric( $cluster_row['identity_count'] ?? null ) ) {
			$projected_count = max( 0, (int) $cluster_row['identity_count'] );
			$observed_count  = count( $member_rows );
			if ( $members_loaded && $projected_count !== $observed_count ) {
				// Cap-hit with more projected than observed is intentional preview
				// truncation, not drift — log only genuine shortfalls (OBS-08).
				$is_expected_truncation = null !== $preview_limit
					&& $preview_limit > 0
					&& $observed_count === $preview_limit
					&& $projected_count > $observed_count;

				if ( ! $is_expected_truncation ) {
					Telemetry::log_line(
						sprintf(
							'[acx] cluster identity count mismatch for %s: projected=%d observed=%d',
							trim( (string) ( $cluster_row['cluster_uuid'] ?? '' ) ),
							$projected_count,
							$observed_count
						)
					);
					if ( 0 === $observed_count ) {
						return 0;
					}
				}
			}

			return $projected_count;
		}

		return count( $member_rows );
	}

	/**
	 * Repository maps omit keys for clusters with zero member rows. When members
	 * were fetched for this page, densify so [] means "none" and key absence
	 * remains reserved for "not fetched" at call sites that skip densify.
	 *
	 * @param array<int,array<string,mixed>> $cluster_rows
	 * @param array<string,array<int,array<string,mixed>>> $members_by_cluster
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	private function densify_members_for_cluster_rows( array $cluster_rows, array $members_by_cluster ): array {
		$dense = array();
		foreach ( $cluster_rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}
			$cluster_id = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			if ( '' === $cluster_id ) {
				continue;
			}
			if ( isset( $members_by_cluster[ $cluster_id ] ) && is_array( $members_by_cluster[ $cluster_id ] ) ) {
				$dense[ $cluster_id ] = $members_by_cluster[ $cluster_id ];
			} else {
				$dense[ $cluster_id ] = array();
			}
		}

		return $dense;
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 */
	private function normalize_label( array $cluster_row ): string {
		return trim( (string) ( $cluster_row['label'] ?? '' ) );
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 * @return array{label: ?string, is_labeled: bool, is_auto_label: bool, user_confirmed: bool}
	 */
	private function resolve_label_state( array $cluster_row ): array {
		$label          = $this->normalize_label( $cluster_row );
		$user_confirmed = $this->resolve_user_confirmed_flag( $cluster_row );
		$is_auto_label  = '' !== $label && ! $user_confirmed && $this->looks_like_system_defined_label( $label );

		return array(
			'label' => ( '' !== $label && ! $is_auto_label ) ? $label : null,
			'is_labeled' => '' !== $label && ! $is_auto_label,
			'is_auto_label' => $is_auto_label,
			'user_confirmed' => $user_confirmed,
		);
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 */
	private function resolve_user_confirmed_flag( array $cluster_row ): bool {
		$value = $cluster_row['is_user_confirmed'] ?? false;
		if ( is_string( $value ) ) {
			$value = trim( $value );
		}
		return in_array( $value, array( true, 1, '1', 'true', 'yes', 'on' ), true );
	}

	private function extract_media_id_from_thumb_path( mixed $thumb_path ): int {
		if ( ! is_string( $thumb_path ) ) {
			return 0;
		}

		if ( ! str_starts_with( $thumb_path, 'acx://' ) ) {
			return 0;
		}

		$parts = explode( '/', $thumb_path );
		$media_index = array_search( 'media', $parts, true );
		if ( false === $media_index ) {
			return 0;
		}

		$media_id = $parts[ $media_index + 1 ] ?? '';
		return absint( $media_id );
	}
}
