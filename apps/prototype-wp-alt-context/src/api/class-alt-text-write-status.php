<?php

declare(strict_types=1);

namespace AltContext\Api;

/**
 * Canonical alt-write outcome statuses for REST describe and CLI generate.
 *
 * Single definition per [sr-007]. Values are byte-identical to the pre-wave
 * wire strings — do not "normalize" CLI/REST divergence in this wave.
 *
 * Path notes:
 * - {@see self::FORCED_OVERWRITE} is emitted by REST force-overwrite success.
 *   The CLI force path deliberately still emits {@see self::WRITTEN}; that
 *   divergence is intentional and out of scope for this wave.
 * - {@see self::DRY_RUN} is CLI-only (generate without --write). REST never
 *   emits it.
 * - {@see self::PARTIAL} alone is ambiguous (BR-08): REST always pairs it with
 *   a {@see self::REASON_*} `reason` field so provenance-stamp failure is
 *   distinguishable from optional long-description failure.
 */
final class AltTextWriteStatus {
	public const WRITTEN                = 'written';
	public const SKIPPED_EXISTING_ALT   = 'skipped_existing_alt';
	public const SKIPPED_EMPTY_ALT_TEXT = 'skipped_empty_alt_text';
	public const FORCED_OVERWRITE       = 'forced_overwrite';
	public const PARTIAL                = 'partial';
	public const FAILED                 = 'failed';

	/**
	 * CLI-only: generate without --write. REST never emits this member.
	 */
	public const DRY_RUN = 'dry_run';

	/**
	 * Partial reason: alt written, provenance stamp failed → item is absent
	 * from history and needs retry (BR-08 / class-describe-media-service).
	 */
	public const REASON_PROVENANCE_WRITE_FAILED = 'provenance_write_failed';

	/**
	 * Partial reason: alt and provenance both landed; only the optional long
	 * description failed → nothing is missing from history (BR-08).
	 */
	public const REASON_DESCRIPTION_WRITE_FAILED = 'description_write_failed';

	/**
	 * Full produced union (REST ∪ CLI).
	 *
	 * @var list<string>
	 */
	public const ALL = array(
		self::WRITTEN,
		self::SKIPPED_EXISTING_ALT,
		self::SKIPPED_EMPTY_ALT_TEXT,
		self::FORCED_OVERWRITE,
		self::PARTIAL,
		self::FAILED,
		self::DRY_RUN,
	);

	/**
	 * Statuses REST may put on `alt_text_write.status` (no dry_run).
	 *
	 * @var list<string>
	 */
	public const REST_STATUSES = array(
		self::WRITTEN,
		self::SKIPPED_EXISTING_ALT,
		self::SKIPPED_EMPTY_ALT_TEXT,
		self::FORCED_OVERWRITE,
		self::PARTIAL,
		self::FAILED,
	);

	/**
	 * Statuses CLI generate may put on each row's `status`.
	 * CLI force-overwrite success is {@see self::WRITTEN}, not FORCED_OVERWRITE.
	 *
	 * @var list<string>
	 */
	public const CLI_STATUSES = array(
		self::WRITTEN,
		self::SKIPPED_EXISTING_ALT,
		self::SKIPPED_EMPTY_ALT_TEXT,
		self::PARTIAL,
		self::FAILED,
		self::DRY_RUN,
	);

	/**
	 * Values for the REST-only `reason` field when status is partial.
	 *
	 * @var list<string>
	 */
	public const PARTIAL_REASONS = array(
		self::REASON_PROVENANCE_WRITE_FAILED,
		self::REASON_DESCRIPTION_WRITE_FAILED,
	);

	private function __construct() {}
}

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
