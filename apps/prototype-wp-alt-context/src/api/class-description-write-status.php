<?php

declare(strict_types=1);

namespace AltContext\Api;

/**
 * Nested `description_write` outcomes when `acx_alt_style` is
 * `alt_plus_description`. Omitted entirely under `alt_only` so the
 * `alt_text_write` payload stays byte-identical to pre-ALTQ-1 behavior.
 *
 * REST-only today (CLI generate does not write long description).
 */
final class DescriptionWriteStatus {
	public const WRITTEN                      = 'written';
	public const FORCED_OVERWRITE             = 'forced_overwrite';
	public const SKIPPED_NO_LONG_TEXT         = 'skipped_no_long_text';
	public const SKIPPED_EXISTING_DESCRIPTION = 'skipped_existing_description';
	public const FAILED                       = 'failed';

	/**
	 * @var list<string>
	 */
	public const ALL = array(
		self::WRITTEN,
		self::FORCED_OVERWRITE,
		self::SKIPPED_NO_LONG_TEXT,
		self::SKIPPED_EXISTING_DESCRIPTION,
		self::FAILED,
	);

	private function __construct() {}
}
