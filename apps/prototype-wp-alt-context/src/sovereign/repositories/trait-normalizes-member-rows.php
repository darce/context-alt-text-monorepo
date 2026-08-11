<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function absint;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function date_create_immutable;
use function is_array;
use function is_numeric;
use function is_string;
use function max;
use function preg_match;
use function round;
use function sprintf;
use function trim;
use function wp_json_encode;

trait NormalizesMemberRows {
	/**
	 * @param array<string,mixed> $member
	 */
	public function normalize_similarity_value( array $member ): string {
		$value = $member['similarity'] ?? $member['match_similarity'] ?? null;
		return $this->normalize_optional_float_value( $value );
	}

	public function normalize_optional_float_value( mixed $value ): string {
		if ( ! is_numeric( $value ) ) {
			return '';
		}

		return (string) (float) $value;
	}

	/**
	 * Normalize recognition assigned_at (ISO-8601 or MySQL datetime) to UTC MySQL form,
	 * PRESERVING sub-second precision (rg-005 / DATA-15 ordering fidelity). Recognition
	 * stores assigned_at as TIMESTAMP(tz) at microsecond resolution and exports it via
	 * isoformat(); truncating to whole seconds would collapse members assigned within the
	 * same second onto the random identity_uuid tie-break and flip PHP order vs recognition.
	 * Falls back to created_at, then $fallback_utc, so ORDER BY assigned_at never sees NULL.
	 *
	 * @param array<string,mixed> $member
	 */
	public function normalize_assigned_at( array $member, string $fallback_utc ): string {
		foreach ( array( $member['assigned_at'] ?? null, $member['created_at'] ?? null ) as $candidate ) {
			if ( ! is_string( $candidate ) ) {
				continue;
			}

			$trimmed = trim( $candidate );
			if ( '' === $trimmed ) {
				continue;
			}

			// Already MySQL-shaped, with or without a fractional part (projection re-hydrate path).
			if ( 1 === preg_match( '/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{1,6})?$/', $trimmed ) ) {
				return $trimmed;
			}

			// Recognition export uses isoformat() (e.g. 2024-01-15T12:30:00.123456+00:00).
			// Parse via DateTimeImmutable (NOT strtotime, which floors to whole seconds) and
			// keep microseconds; normalize any offset to UTC.
			$parsed = date_create_immutable( $trimmed );
			if ( false !== $parsed ) {
				return $parsed->setTimezone( new \DateTimeZone( 'UTC' ) )->format( 'Y-m-d H:i:s.u' );
			}
		}

		return $fallback_utc;
	}

	/**
	 * @param array<string,mixed> $member
	 */
	public function normalize_thumb_path( array $member, string $identity_uuid, int $attachment_id ): string {
		$thumb_path = trim( (string) ( $member['thumb_path'] ?? '' ) );
		if ( '' !== $thumb_path ) {
			return $thumb_path;
		}

		if ( $attachment_id > 0 ) {
			return sprintf( 'acx://identity/%s/attachment/%d', $identity_uuid, $attachment_id );
		}

		return '';
	}

	/**
	 * @param array<string,mixed> $member
	 */
	public function encode_bbox_json( array $member ): string {
		$bbox = $member['bbox'] ?? array();
		if ( ! is_array( $bbox ) ) {
			$bbox = array();
		}

		$pixels = $this->extract_pixels( $bbox );
		$normalized_bbox = $this->extract_normalized_bbox( $bbox, $member, $pixels );
		$payload = array(
			'pixels'           => $pixels,
			'normalized'       => $normalized_bbox,
			'coordinate_space' => 'original_image',
		);

		$json = wp_json_encode( $payload );
		return is_string( $json ) && '' !== $json ? $json : '{}';
	}

	/**
	 * @param array<string,mixed> $bbox
	 * @return array<string,int>
	 */
	public function extract_pixels( array $bbox ): array {
		$source = $bbox['pixels'] ?? $bbox;
		if ( ! is_array( $source ) ) {
			$source = array();
		}

		return array(
			'x'      => max( 0, absint( $source['x'] ?? 0 ) ),
			'y'      => max( 0, absint( $source['y'] ?? 0 ) ),
			'width'  => max( 0, absint( $source['width'] ?? 0 ) ),
			'height' => max( 0, absint( $source['height'] ?? 0 ) ),
		);
	}

	/**
	 * @param array<string,mixed> $bbox
	 * @param array<string,mixed> $member
	 * @param array<string,int> $pixels
	 * @return array<string,float>
	 */
	public function extract_normalized_bbox( array $bbox, array $member, array $pixels ): array {
		$normalized = $bbox['normalized'] ?? null;
		if ( is_array( $normalized )
			&& isset( $normalized['x'], $normalized['y'], $normalized['width'], $normalized['height'] )
			&& is_numeric( $normalized['x'] )
			&& is_numeric( $normalized['y'] )
			&& is_numeric( $normalized['width'] )
			&& is_numeric( $normalized['height'] )
		) {
			return array(
				'x'      => round( (float) $normalized['x'], 6 ),
				'y'      => round( (float) $normalized['y'], 6 ),
				'width'  => round( (float) $normalized['width'], 6 ),
				'height' => round( (float) $normalized['height'], 6 ),
			);
		}

		$image_width  = absint( $member['image_width'] ?? $bbox['image_width'] ?? 0 );
		$image_height = absint( $member['image_height'] ?? $bbox['image_height'] ?? 0 );

		return array(
			'x'      => $image_width > 0 ? round( $pixels['x'] / $image_width, 6 ) : 0.0,
			'y'      => $image_height > 0 ? round( $pixels['y'] / $image_height, 6 ) : 0.0,
			'width'  => $image_width > 0 ? round( $pixels['width'] / $image_width, 6 ) : 0.0,
			'height' => $image_height > 0 ? round( $pixels['height'] / $image_height, 6 ) : 0.0,
		);
	}

	/**
	 * @param string[] $candidate_ids
	 * @return string[]
	 */
	public function sanitize_uuid_list( array $candidate_ids ): array {
		$normalized_ids = array_map(
			static function ( $candidate ): string {
				return trim( (string) $candidate );
			},
			$candidate_ids
		);

		$valid_ids = array_filter(
			$normalized_ids,
			static function ( string $value ): bool {
				return '' !== $value && 1 === preg_match( '/^[A-Za-z0-9-]+$/', $value );
			}
		);

		return array_values( array_unique( $valid_ids ) );
	}
}
