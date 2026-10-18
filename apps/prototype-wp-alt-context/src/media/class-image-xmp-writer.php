<?php

declare(strict_types=1);

namespace AltContext\Media;

require_once dirname( __DIR__ ) . '/support/trait-detects-system-defined-labels.php';

use AltContext\Support\DetectsSystemDefinedLabels;
use function array_values;
use function file_get_contents;
use function file_put_contents;
use function get_post_mime_type;
use function in_array;
use function is_array;
use function is_bool;
use function is_numeric;
use function is_readable;
use function is_string;
use function is_writable;
use function max;
use function min;
use function pathinfo;
use function preg_match;
use function round;
use function strtolower;
use function trim;
use function wp_get_attachment_metadata;

class ImageXmpWriter {
	use DetectsSystemDefinedLabels;

	public const STATUS_WRITTEN = 'written';
	public const STATUS_SKIPPED = 'skipped';
	public const STATUS_FAILED = 'failed';

	private FaceMetricsSourceInterface $faceMetricsSource;
	private XmpImageRegionPacketBuilder $packetBuilder;
	private JpegXmpInjector $jpegInjector;
	private PngXmpInjector $pngInjector;

	public function __construct(
		FaceMetricsSourceInterface $face_metrics_source,
		XmpImageRegionPacketBuilder $packet_builder,
		JpegXmpInjector $jpeg_injector,
		PngXmpInjector $png_injector
	) {
		$this->faceMetricsSource = $face_metrics_source;
		$this->packetBuilder = $packet_builder;
		$this->jpegInjector = $jpeg_injector;
		$this->pngInjector = $png_injector;
	}

	public function write_for_attachment( int $attachment_id, string $original_path ): string {
		if ( $attachment_id <= 0 || '' === $original_path ) {
			return self::STATUS_SKIPPED;
		}

		if ( ! is_readable( $original_path ) || ! is_writable( $original_path ) ) {
			return self::STATUS_FAILED;
		}

		$mime_type = $this->resolve_supported_mime_type( $attachment_id, $original_path );
		if ( null === $mime_type ) {
			return self::STATUS_SKIPPED;
		}

		$identities = $this->faceMetricsSource->get_identities_for_attachment( $attachment_id );
		if ( empty( $identities ) ) {
			return self::STATUS_SKIPPED;
		}

		$regions_by_locator = array();
		foreach ( $identities as $identity ) {
			if ( ! is_array( $identity ) ) {
				continue;
			}

			$region = $this->map_identity_to_xmp_region( $identity, $attachment_id );
			if ( ! is_array( $region ) ) {
				continue;
			}

			$regions_by_locator[ (string) $region['locator_key'] ] = $region;
		}

		if ( empty( $regions_by_locator ) ) {
			return self::STATUS_SKIPPED;
		}

		$binary = file_get_contents( $original_path );
		if ( false === $binary ) {
			return self::STATUS_FAILED;
		}

		$regions = array_values( $regions_by_locator );
		$existing_packet = null;
		$updated_binary = $binary;

		if ( 'image/jpeg' === $mime_type ) {
			$existing_packet = $this->jpegInjector->extract_packet( $binary );
			$new_packet = $this->packetBuilder->build_packet( $regions, $existing_packet );
			if ( '' === $new_packet ) {
				return self::STATUS_FAILED;
			}
			$updated_binary = $this->jpegInjector->inject_packet( $binary, $new_packet );
		}

		if ( 'image/png' === $mime_type ) {
			$existing_packet = $this->pngInjector->extract_packet( $binary );
			$new_packet = $this->packetBuilder->build_packet( $regions, $existing_packet );
			if ( '' === $new_packet ) {
				return self::STATUS_FAILED;
			}
			$updated_binary = $this->pngInjector->inject_packet( $binary, $new_packet );
		}

		if ( $updated_binary === $binary ) {
			return self::STATUS_WRITTEN;
		}

		$written = file_put_contents( $original_path, $updated_binary );
		if ( false === $written ) {
			return self::STATUS_FAILED;
		}

		return self::STATUS_WRITTEN;
	}

	private function resolve_supported_mime_type( int $attachment_id, string $path ): ?string {
		$mime_type = get_post_mime_type( $attachment_id );
		if ( is_string( $mime_type ) ) {
			$normalized_mime = strtolower( trim( $mime_type ) );
			if ( 'image/jpeg' === $normalized_mime || 'image/png' === $normalized_mime ) {
				return $normalized_mime;
			}
		}

		$extension = strtolower( (string) pathinfo( $path, PATHINFO_EXTENSION ) );
		if ( 'jpg' === $extension || 'jpeg' === $extension ) {
			return 'image/jpeg';
		}

		if ( 'png' === $extension ) {
			return 'image/png';
		}

		return null;
	}

	/**
	 * @param array<string,mixed> $identity
	 * @return array<string,mixed>|null
	 */
	private function map_identity_to_xmp_region( array $identity, int $attachment_id ): ?array {
		$label = trim( (string) ( $identity['cluster_label'] ?? '' ) );
		if ( ! $this->should_persist_identity_label( $identity, $label ) ) {
			return null;
		}

		$metadata = wp_get_attachment_metadata( $attachment_id, true );
		if ( ! is_array( $metadata ) ) {
			return null;
		}

		$image_width = (int) ( $metadata['width'] ?? 0 );
		$image_height = (int) ( $metadata['height'] ?? 0 );
		if ( $image_width <= 0 || $image_height <= 0 ) {
			return null;
		}

		$bbox = $identity['bbox'] ?? null;
		if ( ! is_array( $bbox ) ) {
			return null;
		}

		$x = (float) ( $bbox['x'] ?? 0.0 );
		$y = (float) ( $bbox['y'] ?? 0.0 );
		$width = (float) ( $bbox['width'] ?? 0.0 );
		$height = (float) ( $bbox['height'] ?? 0.0 );
		if ( $width <= 0 || $height <= 0 ) {
			return null;
		}

		$metrics = is_array( $identity['debug_metrics'] ?? null ) ? $identity['debug_metrics'] : array();
		$pose = is_array( $metrics['pose'] ?? null ) ? $metrics['pose'] : array();

		return array(
			'name' => $label,
			'locator_key' => $this->build_locator_key( $x, $y, $width, $height ),
			// IPTC rectangle shape defines rbX/rbY as center point, not top-left.
			'rbX' => round( $this->clamp_normalized( ( $x + ( $width / 2.0 ) ) / (float) $image_width ), 6 ),
			'rbY' => round( $this->clamp_normalized( ( $y + ( $height / 2.0 ) ) / (float) $image_height ), 6 ),
			'rbW' => round( $this->clamp_normalized( $width / (float) $image_width ), 6 ),
			'rbH' => round( $this->clamp_normalized( $height / (float) $image_height ), 6 ),
			'acx_pitch' => $this->as_nullable_float( $pose['pitch'] ?? null ),
			'acx_yaw' => $this->as_nullable_float( $pose['yaw'] ?? null ),
			'acx_roll' => $this->as_nullable_float( $pose['roll'] ?? null ),
			'acx_det_score' => $this->as_nullable_float( $metrics['det_score'] ?? null ),
			'acx_landmark_quality' => $this->as_nullable_float( $metrics['landmark_quality'] ?? null ),
		);
	}

	private function build_locator_key( float $x, float $y, float $width, float $height ): string {
		return $x . ':' . $y . ':' . $width . ':' . $height;
	}

	private function clamp_normalized( float $value ): float {
		return max( 0.0, min( 1.0, $value ) );
	}

	/**
	 * @param mixed $value
	 */
	private function as_nullable_float( $value ): ?float {
		if ( ! is_numeric( $value ) ) {
			return null;
		}

		return (float) $value;
	}

	/**
	 * @param array<string,mixed> $identity
	 */
	private function should_persist_identity_label( array $identity, string $label ): bool {
		if ( '' === $label ) {
			return false;
		}

		if ( $this->is_truthy( $identity['is_auto_label'] ?? null ) ) {
			// Auto/system labels are not curated and should not be persisted.
			return false;
		}

		$cluster_id = trim( (string) ( $identity['cluster_id'] ?? '' ) );
		if ( '' !== $cluster_id && $label === $cluster_id ) {
			return false;
		}

		// Avoid writing raw UUID identifiers as human-readable labels.
		if ( 1 === preg_match( '/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i', $label ) ) {
			return false;
		}

		if ( $this->looks_like_system_defined_label( $label ) ) {
			return false;
		}

		return true;
	}

	/**
	 * @param mixed $value
	 */
	private function is_truthy( $value ): bool {
		if ( is_bool( $value ) ) {
			return true === $value;
		}

		if ( is_numeric( $value ) ) {
			return 1 === (int) $value;
		}

		$normalized = strtolower( trim( (string) $value ) );
		return in_array( $normalized, array( '1', 'true', 'yes', 'on' ), true );
	}
}
