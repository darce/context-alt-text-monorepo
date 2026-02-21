<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

use function absint;
use function is_array;
use function is_numeric;
use function is_string;
use function json_decode;
use function strpos;
use function trim;
use function wp_get_attachment_url;

/**
 * Shared response field mapping helpers used by both ClusterResponseMapper
 * and MemberResponseMapper.
 */
trait MapsResponseFields {
	/**
	 * Resolve thumbnail URL from thumb_path or WordPress attachment fallback.
	 *
	 * @param array<string,mixed> $member_row
	 */
	private function resolve_thumb_url( array $member_row, int $media_id ): ?string {
		if ( $media_id > 0 ) {
			$attachment_url = wp_get_attachment_url( $media_id );
			if ( is_string( $attachment_url ) && '' !== trim( $attachment_url ) ) {
				return $attachment_url;
			}
		}

		return null;
	}

	/**
	 * Resolve media URL from WordPress attachment.
	 */
	private function resolve_media_url( int $media_id ): ?string {
		if ( $media_id <= 0 ) {
			return null;
		}

		$attachment_url = wp_get_attachment_url( $media_id );
		if ( is_string( $attachment_url ) && '' !== trim( $attachment_url ) ) {
			return $attachment_url;
		}

		return null;
	}

	/**
	 * Extract bbox_pixels from bbox JSON.
	 *
	 * @param mixed $bbox_json
	 * @return array<string,int>
	 */
	private function extract_bbox_pixels( mixed $bbox_json ): array {
		if ( ! is_string( $bbox_json ) || '' === trim( $bbox_json ) ) {
			return array( 'x' => 0, 'y' => 0, 'width' => 0, 'height' => 0 );
		}

		$decoded = json_decode( $bbox_json, true );
		if ( ! is_array( $decoded ) ) {
			return array( 'x' => 0, 'y' => 0, 'width' => 0, 'height' => 0 );
		}

		$pixels = $decoded['pixels'] ?? $decoded;
		if ( ! is_array( $pixels ) ) {
			return array( 'x' => 0, 'y' => 0, 'width' => 0, 'height' => 0 );
		}

		return array(
			'x' => absint( $pixels['x'] ?? 0 ),
			'y' => absint( $pixels['y'] ?? 0 ),
			'width' => absint( $pixels['width'] ?? 0 ),
			'height' => absint( $pixels['height'] ?? 0 ),
		);
	}

	/**
	 * Normalize similarity value from member row.
	 *
	 * @param array<string,mixed> $member_row
	 */
	private function normalize_similarity_value( array $member_row ): float {
		$value = $member_row['similarity'] ?? null;
		if ( ! is_numeric( $value ) ) {
			return 0.0;
		}

		return (float) $value;
	}

	/**
	 * Normalize confidence value from member row, falling back to similarity.
	 *
	 * @param array<string,mixed> $member_row
	 */
	private function normalize_confidence_value( array $member_row ): float {
		$value = $member_row['confidence'] ?? $member_row['similarity'] ?? null;
		if ( ! is_numeric( $value ) ) {
			return 0.0;
		}

		return (float) $value;
	}
}
