<?php

declare(strict_types=1);

namespace AltContext\Api;

use function array_is_list;
use function get_option;
use function in_array;
use function is_array;
use function is_string;

/**
 * Canonical names and settings resolution for outbound context categories.
 */
final class ContextCategoryPolicy {
	public const OPTION_NAME = 'acx_description_context_categories';

	public const ATTACHMENT     = 'attachment';
	public const POST           = 'post';
	public const TAXONOMY_TERMS = 'taxonomy_terms';
	public const PRODUCT        = 'product';

	public const ALL = array(
		self::ATTACHMENT,
		self::POST,
		self::TAXONOMY_TERMS,
		self::PRODUCT,
	);

	/**
	 * Validate the list accepted by the settings endpoint.
	 *
	 * @param mixed $value Candidate value.
	 */
	public static function is_valid_list( mixed $value ): bool {
		if ( ! is_array( $value ) || ! array_is_list( $value ) ) {
			return false;
		}

		$seen = array();
		foreach ( $value as $category ) {
			if (
				! is_string( $category )
				|| ! in_array( $category, self::ALL, true )
				|| in_array( $category, $seen, true )
			) {
				return false;
			}

			$seen[] = $category;
		}

		return true;
	}

	/**
	 * Return known names in the canonical order, removing duplicate entries.
	 *
	 * @param string[] $names Category names.
	 * @return string[]
	 */
	public static function canonical( array $names ): array {
		$canonical = array();
		foreach ( self::ALL as $category ) {
			if ( in_array( $category, $names, true ) ) {
				$canonical[] = $category;
			}
		}

		return $canonical;
	}

	/**
	 * Resolve the settings GET fields from the stored option.
	 *
	 * A legacy stored array may contain duplicate names or non-list keys; the
	 * describe service has historically accepted such arrays when every value
	 * names a supported category, so GET keeps them valid and canonicalizes them.
	 *
	 * @return array{categories: string[]|null, error: string|null}
	 */
	public static function resolve(): array {
		$missing = new \stdClass();
		$stored  = get_option( self::OPTION_NAME, $missing );
		if ( $missing === $stored ) {
			return array(
				'categories' => null,
				'error'      => null,
			);
		}

		if ( self::is_valid_stored_value( $stored ) ) {
			return array(
				'categories' => self::canonical( $stored ),
				'error'      => null,
			);
		}

		return array(
			'categories' => array( self::ATTACHMENT ),
			'error'      => 'Stored context categories value is invalid; only attachment details are sent.',
		);
	}

	/**
	 * Preserve the describe service's legacy validity rule for stored values.
	 *
	 * @param mixed $value Stored option value.
	 */
	private static function is_valid_stored_value( mixed $value ): bool {
		if ( ! is_array( $value ) ) {
			return false;
		}

		foreach ( $value as $category ) {
			if ( ! is_string( $category ) || ! in_array( $category, self::ALL, true ) ) {
				return false;
			}
		}

		return true;
	}

	private function __construct() {}
}
