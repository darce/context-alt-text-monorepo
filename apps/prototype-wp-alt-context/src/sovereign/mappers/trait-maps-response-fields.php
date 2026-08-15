<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

require_once dirname( __DIR__, 2 ) . '/support/trait-detects-system-defined-labels.php';
require_once dirname( __DIR__, 2 ) . '/api/class-blob-url-rewriter.php';

use AltContext\Api\BlobUrlRewriter;
use AltContext\Support\DetectsSystemDefinedLabels;
use function absint;
use function is_array;
use function is_bool;
use function is_numeric;
use function is_string;
use function in_array;
use function json_decode;
use function strpos;
use function strtolower;
use function trim;
use function wp_get_attachment_url;

/**
 * Shared response field mapping helpers used by both ClusterResponseMapper
 * and MemberResponseMapper.
 */
trait MapsResponseFields {
	use DetectsSystemDefinedLabels;

	/**
	 * Resolve thumbnail URL from thumb_path or WordPress attachment fallback.
	 *
	 * Face-thumbs blob URLs stay first-choice (STOR-07). Callers must also emit
	 * resolve_media_url() as attachment_url and extract_bbox_pixels() so clients
	 * can crop the durable WP attachment after scan-time blobs are deleted.
	 *
	 * @param array<string,mixed> $member_row
	 */
	private function resolve_thumb_url( array $member_row, int $media_id ): ?string {
		$blob_backed_url = $this->resolve_blob_backed_url( $member_row['thumb_path'] ?? null );
		if ( is_string( $blob_backed_url ) && '' !== trim( $blob_backed_url ) && false !== strpos( $blob_backed_url, '/recognition/face-thumbs/' ) ) {
			return $blob_backed_url;
		}

		$attachment_url = $this->resolve_media_url( $media_id );
		if ( is_string( $attachment_url ) && '' !== trim( $attachment_url ) ) {
			return $attachment_url;
		}

		return $blob_backed_url;
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

	private function resolve_blob_backed_url( mixed $value ): ?string {
		if ( ! is_string( $value ) || '' === trim( $value ) ) {
			return null;
		}

		$trimmed = trim( $value );
		$rewritten = BlobUrlRewriter::rewrite_string( $trimmed );
		if ( '' === trim( $rewritten ) ) {
			return null;
		}

		if ( $rewritten !== $trimmed || str_starts_with( $rewritten, 'http://' ) || str_starts_with( $rewritten, 'https://' ) || str_starts_with( $rewritten, '/' ) ) {
			return $rewritten;
		}

		return null;
	}

	/**
	 * Extract bbox pixels from bbox JSON.
	 *
	 * Unknown / undecodable source is null — never a fabricated zero box (rg-015).
	 *
	 * @param mixed $bbox_json
	 * @return array{x:int,y:int,width:int,height:int}|null
	 */
	private function extract_bbox_pixels( mixed $bbox_json ): ?array {
		if ( ! is_string( $bbox_json ) || '' === trim( $bbox_json ) ) {
			return null;
		}

		$decoded = json_decode( $bbox_json, true );
		if ( ! is_array( $decoded ) ) {
			return null;
		}

		$pixels = $decoded['pixels'] ?? $decoded;
		if ( ! is_array( $pixels ) ) {
			return null;
		}

		if ( ! isset( $pixels['x'], $pixels['y'], $pixels['width'], $pixels['height'] ) ) {
			return null;
		}

		if (
			! is_numeric( $pixels['x'] )
			|| ! is_numeric( $pixels['y'] )
			|| ! is_numeric( $pixels['width'] )
			|| ! is_numeric( $pixels['height'] )
		) {
			return null;
		}

		$width  = (int) $pixels['width'];
		$height = (int) $pixels['height'];
		if ( $width <= 0 || $height <= 0 ) {
			return null;
		}

		return array(
			'x' => absint( $pixels['x'] ),
			'y' => absint( $pixels['y'] ),
			'width' => $width,
			'height' => $height,
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

	private function normalize_boolean_value( mixed $value ): bool {
		if ( is_bool( $value ) ) {
			return $value;
		}

		if ( is_numeric( $value ) ) {
			return 0 !== (int) $value;
		}

		if ( is_string( $value ) ) {
			$normalized = strtolower( trim( $value ) );
			if ( in_array( $normalized, array( '1', 'true', 'yes', 'on' ), true ) ) {
				return true;
			}
		}

		return false;
	}
}
