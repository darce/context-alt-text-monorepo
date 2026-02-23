<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

use function absint;
use function is_array;
use function is_numeric;
use function is_string;
use function json_decode;
use function trim;
use function wp_get_attachment_url;

class MemberResponseMapper {
	use MapsResponseFields;

	/**
	 * @param array<int,array<string,mixed>> $member_rows
	 * @return array<int,array<string,mixed>>
	 */
	public function map_cluster_members( array $member_rows ): array {
		$results = array();
		foreach ( $member_rows as $row ) {
			$results[] = $this->map_cluster_identity( $row );
		}

		return $results;
	}

	/**
	 * @param array<int,array<string,mixed>> $member_rows
	 * @return array<string,array<int,array<string,mixed>>>
	 */
	public function map_media_identities( array $member_rows ): array {
		$grouped = array();
		foreach ( $member_rows as $row ) {
			$media_id = absint( $row['attachment_id'] ?? $row['media_id'] ?? 0 );
			if ( $media_id <= 0 ) {
				continue;
			}

			$key = (string) $media_id;
			if ( ! isset( $grouped[ $key ] ) ) {
				$grouped[ $key ] = array();
			}

			$grouped[ $key ][] = $this->map_cluster_identity( $row );
		}

		return $grouped;
	}

	/**
	 * @param array<string,mixed> $member_row
	 * @return array<string,mixed>
	 */
	private function map_cluster_identity( array $member_row ): array {
		$media_id = absint( $member_row['attachment_id'] ?? $member_row['media_id'] ?? 0 );

		return array(
			'identity_id' => trim( (string) ( $member_row['identity_uuid'] ?? '' ) ),
			'media_id' => $media_id,
			'similarity' => $this->normalize_similarity_value( $member_row ),
			'confidence' => $this->normalize_confidence_value( $member_row ),
			'clustering_pending' => false,
			'bbox' => $this->extract_bbox_pixels( $member_row['bbox_json'] ?? null ),
			'thumb_url'     => $this->resolve_thumb_url( $member_row, $media_id ),
			'media_url'     => $this->resolve_media_url( $media_id ),
			'cluster_id' => $this->normalize_cluster_id( $member_row ),
			'cluster_label' => $this->normalize_cluster_label( $member_row ),
			'is_auto_label' => false,
			'is_pinned' => false,
			'detected_at' => null,
			'representative_id' => null,
			'debug_metrics' => null,
		);
	}



	private function normalize_cluster_id( array $member_row ): ?string {
		$cluster_id = trim( (string) ( $member_row['cluster_uuid'] ?? '' ) );
		return '' !== $cluster_id ? $cluster_id : null;
	}

	private function normalize_cluster_label( array $member_row ): ?string {
		$label = trim( (string) ( $member_row['cluster_label'] ?? '' ) );
		return '' !== $label ? $label : null;
	}
}
