<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

require_once __DIR__ . '/trait-maps-response-fields.php';

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
	 * @return array<int,array<string,mixed>>
	 */
	public function map_cluster_list( array $cluster_rows, array $members_by_cluster ): array {
		$results = array();

		foreach ( $cluster_rows as $row ) {
			$cluster_id = trim( (string) ( $row['cluster_uuid'] ?? '' ) );
			$members    = array();
			if ( '' !== $cluster_id && isset( $members_by_cluster[ $cluster_id ] ) && is_array( $members_by_cluster[ $cluster_id ] ) ) {
				$members = $members_by_cluster[ $cluster_id ];
			}
			$results[] = $this->map_cluster_summary( $row, $members );
		}

		return $results;
	}

	/**
	 * @param array<string,mixed> $cluster_row
	 * @param array<int,array<string,mixed>> $member_rows
	 * @return array<string,mixed>
	 */
	public function map_cluster_detail( array $cluster_row, array $member_rows ): array {
		return $this->map_cluster_summary( $cluster_row, $member_rows );
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
	 * @return array<int,array<string,mixed>>
	 */
	public function map_top_unlabeled_clusters( array $cluster_rows, array $members_by_cluster, string $tenant_id ): array {
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
				'identity_count' => $this->resolve_identity_count( $row, $members ),
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
	 * @return array<string,mixed>
	 */
	private function map_cluster_summary( array $cluster_row, array $member_rows ): array {
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

		return array(
			'id' => $cluster_id,
			'label' => $label_state['label'],
			'is_auto_label' => $label_state['is_auto_label'],
			'identity_count' => $this->resolve_identity_count( $cluster_row, $members ),
			'member_ids' => $member_ids,
			'representative_identity' => $representative,
			'sample_identities' => $sample_identities,
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
	 */
	private function resolve_identity_count( array $cluster_row, array $member_rows ): int {
		if ( is_numeric( $cluster_row['identity_count'] ?? null ) ) {
			return max( 0, (int) $cluster_row['identity_count'] );
		}

		return count( $member_rows );
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
