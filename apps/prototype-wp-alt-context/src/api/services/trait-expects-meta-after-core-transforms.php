<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function apply_filters;
use function function_exists;
use function sanitize_meta;
use function wp_unslash;

/**
 * Shared model of what update_metadata() will compare/store after core
 * transforms (wp_unslash then sanitize_meta). Used by describe-media alt/provenance
 * read-back and description-history correction so a single sanitize model
 * governs every meta read-back [F-08 / R16-BR-15].
 */
trait ExpectsMetaAfterCoreTransforms {

	/**
	 * Value update_metadata() will compare/store: wp_unslash then sanitize_meta.
	 *
	 * Prefer sanitize_meta() when present (production WP). The unit harness
	 * stubs do not define it; fall back to the same sanitize_{type}_meta_{key}
	 * filter chain sanitize_meta dispatches for post meta without a subtype
	 * filter. Do not invent a second sanitizer. [R16-BR-15] [rg-015]
	 *
	 * @param mixed $value Pre-transform value passed to update_post_meta.
	 * @return mixed
	 */
	private function expected_meta_after_core_transforms( string $meta_key, $value ) {
		$value = wp_unslash( $value );
		if ( function_exists( 'sanitize_meta' ) ) {
			return sanitize_meta( $meta_key, $value, 'post' );
		}

		return apply_filters( 'sanitize_post_meta_' . $meta_key, $value, $meta_key, 'post' );
	}
}
