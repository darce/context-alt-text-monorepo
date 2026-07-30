<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use function apply_filters;
use function function_exists;
use function has_filter;
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
	 * Prefer sanitize_meta() when present (production WP). When absent, fall
	 * back to the same filter dispatch sanitize_meta uses in
	 * wp-includes/meta.php — including the subtype-scoped hook
	 * sanitize_{type}_meta_{key}_for_{subtype}. Do not invent a second
	 * sanitizer. [R16-BR-15] [rg-015] [R20-BR-10] [R20-BR-12]
	 *
	 * Object subtype is `attachment`: every surface that uses this trait writes
	 * post meta on attachments, and update_metadata() resolves that via
	 * get_object_subtype( 'post', $id ). Passing the subtype enables
	 * sanitize_post_meta_{$key}_for_attachment (invisible without it).
	 *
	 * @param mixed $value Pre-transform value passed to update_post_meta.
	 * @return mixed
	 */
	private function expected_meta_after_core_transforms( string $meta_key, $value ) {
		$value          = wp_unslash( $value );
		$object_subtype = 'attachment';

		if ( function_exists( 'sanitize_meta' ) ) {
			return sanitize_meta( $meta_key, $value, 'post', $object_subtype );
		}

		return $this->apply_sanitize_meta_filters( $meta_key, $value, $object_subtype );
	}

	/**
	 * Filter-chain model of sanitize_meta() when the function is absent.
	 * Mirrors wp-includes/meta.php sanitize_meta() dispatch order and args.
	 *
	 * @param mixed $value Already-unslashed meta value.
	 * @return mixed
	 */
	private function apply_sanitize_meta_filters( string $meta_key, $value, string $object_subtype = '' ) {
		if ( '' !== $object_subtype
			&& function_exists( 'has_filter' )
			&& has_filter( "sanitize_post_meta_{$meta_key}_for_{$object_subtype}" )
		) {
			return apply_filters(
				"sanitize_post_meta_{$meta_key}_for_{$object_subtype}",
				$value,
				$meta_key,
				'post',
				$object_subtype
			);
		}

		return apply_filters( 'sanitize_post_meta_' . $meta_key, $value, $meta_key, 'post' );
	}
}
