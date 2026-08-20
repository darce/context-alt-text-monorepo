<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

require_once __DIR__ . '/trait-maps-response-fields.php';

use function absint;
use function is_string;
use function trim;

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
	 * @return array<int,list<array<string,mixed>>> Media-id-keyed groups; PHP coerces the numeric string key to int.
	 */
	/**
	 * @param array<string,mixed> $identity
	 * @return array<string,mixed>
	 */
	public function apply_label_authority( array $identity ): array {
		$identity['cluster_label'] = $this->normalize_cluster_label(
			array(
				'person_name'   => $identity['person_name'] ?? '',
				'cluster_label' => is_string( $identity['cluster_label'] ?? null ) ? $identity['cluster_label'] : '',
			)
		);
		$identity['label_state'] = $this->resolve_emitted_label_state( $identity );

		return $identity;
	}

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
		$representative_id = trim( (string) ( $member_row['representative_id'] ?? '' ) );
		$identity_id = trim( (string) ( $member_row['identity_uuid'] ?? '' ) );
		$is_pinned = $this->normalize_boolean_value( $member_row['is_pinned'] ?? false );
		if ( ! $is_pinned && '' !== $representative_id && $representative_id === $identity_id ) {
			$is_pinned = true;
		}

		$cluster_label  = $this->normalize_cluster_label( $member_row );
		$is_auto_label  = '' !== (string) $cluster_label
			&& ! $this->normalize_boolean_value( $member_row['is_user_confirmed'] ?? false )
			&& $this->looks_like_system_defined_label( (string) $cluster_label );

		$source = $this->resolve_face_source_fields( $member_row, $media_id, $member_row['bbox_json'] ?? null );

		return array(
			'identity_id' => $identity_id,
			'media_id' => $media_id,
			'similarity' => $this->normalize_similarity_value( $member_row ),
			'confidence' => $this->normalize_confidence_value( $member_row ),
			'clustering_pending' => false,
			'bbox' => $source['bbox'],
			'thumb_url'     => $source['thumb_url'],
			'attachment_url' => $source['attachment_url'],
			'media_url'     => $source['media_url'],
			'cluster_id' => $this->normalize_cluster_id( $member_row ),
			'cluster_label' => $cluster_label,
			'label_state' => $this->resolve_emitted_label_state( $member_row ),
			'is_auto_label' => $is_auto_label,
			'is_pinned' => $is_pinned,
			'detected_at' => null,
			'representative_id' => '' !== $representative_id ? $representative_id : null,
			'debug_metrics' => null,
		);
	}



	private function normalize_cluster_id( array $member_row ): ?string {
		$cluster_id = trim( (string) ( $member_row['cluster_uuid'] ?? '' ) );
		return '' !== $cluster_id ? $cluster_id : null;
	}

	private function normalize_cluster_label( array $member_row ): ?string {
		$person = trim( (string) ( $member_row['person_name'] ?? '' ) );
		if ( '' !== $person ) {
			return $person;
		}

		$label = trim( (string) ( $member_row['cluster_label'] ?? '' ) );
		if ( '' === $label ) {
			return null;
		}

		if ( $this->is_reserved_label_shape( $label ) ) {
			return $label;
		}

		return null;
	}
}
