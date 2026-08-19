<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Mappers;

require_once dirname( __DIR__, 2 ) . '/support/trait-detects-system-defined-labels.php';
require_once dirname( __DIR__, 2 ) . '/api/class-blob-url-rewriter.php';

use AltContext\Api\BlobUrlRewriter;
use AltContext\Support\DetectsSystemDefinedLabels;
use function absint;
use function dirname;
use function file_exists;
use function get_attached_file;
use function is_array;
use function is_bool;
use function is_dir;
use function is_numeric;
use function is_string;
use function in_array;
use function json_decode;
use function max;
use function round;
use function strpos;
use function strtolower;
use function trim;
use function wp_get_attachment_image_src;
use function wp_get_attachment_metadata;
use function wp_get_attachment_url;

/**
 * Shared response field mapping helpers used by both ClusterResponseMapper
 * and MemberResponseMapper.
 */
trait MapsResponseFields {
	use DetectsSystemDefinedLabels;

	/**
	 * Resolve the four face-source fields as one consistent set.
	 *
	 * URL and bbox must be resolved together: the client crops with a CSS
	 * transform that reads the bbox as natural pixels of the image it loaded,
	 * so emitting a sub-size URL beside an original-space bbox would be
	 * fabricated contract metadata (rg-015). One resolver keeps every mapper
	 * structurally unable to emit a disagreeing pair (ARCH-13).
	 *
	 * @param array<string,mixed> $member_row
	 * @return array{thumb_url:?string,attachment_url:?string,media_url:?string,bbox:array{x:int,y:int,width:int,height:int}|null}
	 */
	private function resolve_face_source_fields( array $member_row, int $media_id, mixed $bbox_json ): array {
		$media = $this->resolve_media_source( $media_id, $this->extract_bbox_pixels( $bbox_json ) );

		return array(
			'thumb_url' => $this->resolve_thumb_url( $member_row, $media['url'] ),
			'attachment_url' => $media['url'],
			'media_url' => $media['url'],
			'bbox' => $media['bbox'],
		);
	}

	/**
	 * Resolve thumbnail URL from thumb_path or WordPress attachment fallback.
	 *
	 * Face-thumbs blob URLs stay first-choice (STOR-07). Callers must also emit
	 * the resolved media URL as attachment_url and the paired bbox so clients
	 * can crop the durable WP attachment after scan-time blobs are deleted.
	 *
	 * @param array<string,mixed> $member_row
	 */
	private function resolve_thumb_url( array $member_row, ?string $media_url ): ?string {
		$blob_backed_url = $this->resolve_blob_backed_url( $member_row['thumb_path'] ?? null );
		if ( is_string( $blob_backed_url ) && '' !== trim( $blob_backed_url ) && false !== strpos( $blob_backed_url, '/recognition/face-thumbs/' ) ) {
			return $blob_backed_url;
		}

		if ( is_string( $media_url ) && '' !== trim( $media_url ) ) {
			return $media_url;
		}

		return $blob_backed_url;
	}

	/**
	 * Resolve a servable media URL together with a bbox in that URL's pixel space.
	 *
	 * `wp_get_attachment_url()` derives a URL from `_wp_attached_file` and never
	 * checks the disk, so a deleted original yields a 404 the client can only
	 * render as a loud error. Prefer the largest surviving registered sub-size
	 * and rescale the bbox into it; a deleted original is expected attrition,
	 * not an operator-actionable fault (OBS-04, PERC-07).
	 *
	 * Degradation only fires on positive evidence that this attachment is stored
	 * locally (its upload directory exists). Without that evidence — offloaded
	 * media, filtered URLs — the unmodified attachment URL is returned, because
	 * absence of a local file is not proof the URL is dead.
	 *
	 * @param array{x:int,y:int,width:int,height:int}|null $bbox
	 * @return array{url:?string,bbox:array{x:int,y:int,width:int,height:int}|null}
	 */
	private function resolve_media_source( int $media_id, ?array $bbox ): array {
		$attachment_url = $this->resolve_media_url( $media_id );
		if ( null === $attachment_url ) {
			return array(
				'url' => null,
				'bbox' => $bbox,
			);
		}

		$original_path = get_attached_file( $media_id );
		if ( ! is_string( $original_path ) || '' === trim( $original_path ) ) {
			return array(
				'url' => $attachment_url,
				'bbox' => $bbox,
			);
		}

		if ( file_exists( $original_path ) ) {
			return array(
				'url' => $attachment_url,
				'bbox' => $bbox,
			);
		}

		$upload_dir = dirname( $original_path );
		if ( ! is_dir( $upload_dir ) ) {
			return array(
				'url' => $attachment_url,
				'bbox' => $bbox,
			);
		}

		$surviving = $this->resolve_largest_surviving_size( $media_id, $upload_dir );
		if ( null === $surviving ) {
			return array(
				'url' => null,
				'bbox' => null,
			);
		}

		if ( null === $bbox ) {
			return array(
				'url' => $surviving['url'],
				'bbox' => null,
			);
		}

		return array(
			'url' => $surviving['url'],
			'bbox' => $this->scale_bbox_pixels( $bbox, $surviving['scale'] ),
		);
	}

	/**
	 * Largest registered sub-size whose file is still on disk, with the scale
	 * factor from the attachment's own pixel space into that sub-size.
	 *
	 * @return array{url:string,scale:?float}|null
	 */
	private function resolve_largest_surviving_size( int $media_id, string $upload_dir ): ?array {
		$metadata = wp_get_attachment_metadata( $media_id );
		if ( ! is_array( $metadata ) ) {
			return null;
		}

		$sizes = $metadata['sizes'] ?? null;
		if ( ! is_array( $sizes ) ) {
			return null;
		}

		$best_name  = null;
		$best_width = 0;
		foreach ( $sizes as $size_name => $size ) {
			if ( ! is_array( $size ) ) {
				continue;
			}

			$file  = $size['file'] ?? null;
			$width = $size['width'] ?? null;
			if ( ! is_string( $file ) || '' === trim( $file ) || ! is_numeric( $width ) ) {
				continue;
			}

			$width = (int) $width;
			if ( $width <= 0 || $width <= $best_width ) {
				continue;
			}

			if ( ! file_exists( $upload_dir . '/' . $file ) ) {
				continue;
			}

			$best_name  = (string) $size_name;
			$best_width = $width;
		}

		if ( null === $best_name ) {
			return null;
		}

		$src = wp_get_attachment_image_src( $media_id, $best_name );
		if ( ! is_array( $src ) || ! isset( $src[0] ) || ! is_string( $src[0] ) || '' === trim( $src[0] ) ) {
			return null;
		}

		$attachment_width = $metadata['width'] ?? null;
		$scale = is_numeric( $attachment_width ) && (int) $attachment_width > 0
			? $best_width / (int) $attachment_width
			: null;

		return array(
			'url' => $src[0],
			'scale' => $scale,
		);
	}

	/**
	 * Project a bbox into a rescaled image. An unknown scale yields null rather
	 * than a bbox in the wrong pixel space (rg-015).
	 *
	 * @param array{x:int,y:int,width:int,height:int} $bbox
	 * @return array{x:int,y:int,width:int,height:int}|null
	 */
	private function scale_bbox_pixels( array $bbox, ?float $scale ): ?array {
		if ( null === $scale || $scale <= 0.0 ) {
			return null;
		}

		if ( 1.0 === $scale ) {
			return $bbox;
		}

		$width  = (int) round( $bbox['width'] * $scale );
		$height = (int) round( $bbox['height'] * $scale );
		if ( $width <= 0 || $height <= 0 ) {
			return null;
		}

		return array(
			'x' => (int) max( 0, round( $bbox['x'] * $scale ) ),
			'y' => (int) max( 0, round( $bbox['y'] * $scale ) ),
			'width' => $width,
			'height' => $height,
		);
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

	/**
	 * Prefer the SQL `label_state` column. Older SELECTs without it still emit
	 * the key via resolve_cluster_label_state() so the FE is never missing it.
	 *
	 * @param array<string,mixed> $row
	 */
	protected function resolve_emitted_label_state( array $row ): string {
		if ( isset( $row['label_state'] ) && is_string( $row['label_state'] ) ) {
			$from_row = trim( $row['label_state'] );
			if ( '' !== $from_row ) {
				return $from_row;
			}
		}

		$person_name = trim( (string) ( $row['person_name'] ?? '' ) );
		if ( '' === $person_name ) {
			$person_uuid = trim( (string) ( $row['person_uuid'] ?? '' ) );
			$projected   = $this->projected_row_label( $row );
			if ( '' !== $person_uuid && '' !== $projected && ! $this->is_reserved_label_shape( $projected ) ) {
				$person_name = $projected;
			}
		}

		$cluster_label = $this->projected_row_label( $row );

		return $this->resolve_cluster_label_state(
			'' !== $person_name ? $person_name : null,
			'' !== $cluster_label ? $cluster_label : null
		);
	}

	/**
	 * Cluster rows expose `label`; member rows expose `cluster_label`.
	 *
	 * @param array<string,mixed> $row
	 */
	protected function projected_row_label( array $row ): string {
		if ( isset( $row['label'] ) && is_string( $row['label'] ) ) {
			return trim( $row['label'] );
		}

		return trim( (string) ( $row['cluster_label'] ?? '' ) );
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
