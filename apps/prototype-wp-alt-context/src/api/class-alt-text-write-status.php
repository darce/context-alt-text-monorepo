<?php

declare(strict_types=1);

namespace AltContext\Api;

/**
 * Canonical alt-write outcome statuses for REST describe and CLI generate.
 *
 * Single definition per [sr-007]. Values are byte-identical to the pre-wave
 * wire strings.
 *
 * Path notes:
 * - {@see self::FORCED_OVERWRITE} is emitted by REST and CLI force-overwrite
 *   success when `force` is true and an existing non-empty alt was present.
 * - {@see self::PROVENANCE_HEALED} is success when force=false and the stored
 *   alt already matched the draft; only provenance was (re)stamped. Emitted by
 *   both REST describe and CLI generate (shared write gate) [F-01].
 * - {@see self::DRY_RUN} is CLI-only (generate without --write). REST never
 *   emits it.
 * - {@see self::PARTIAL} alone is ambiguous (BR-08): REST always pairs it with
 *   a {@see self::REASON_*} `reason` field so provenance-stamp failure is
 *   distinguishable from optional long-description failure. CLI generate pairs
 *   partial with {@see self::REASON_PROVENANCE_WRITE_FAILED} only.
 */
final class AltTextWriteStatus {
	public const WRITTEN                = 'written';
	public const SKIPPED_EXISTING_ALT   = 'skipped_existing_alt';
	public const SKIPPED_EMPTY_ALT_TEXT = 'skipped_empty_alt_text';
	public const FORCED_OVERWRITE       = 'forced_overwrite';
	public const PROVENANCE_HEALED      = 'provenance_healed';
	public const PARTIAL                = 'partial';
	public const FAILED                 = 'failed';

	/**
	 * CLI-only: generate without --write. REST never emits this member.
	 */
	public const DRY_RUN = 'dry_run';

	/**
	 * Partial reason: alt written, provenance stamp failed → item is absent
	 * from history and needs retry (BR-08 / class-describe-media-service).
	 * Emitted by both REST describe and CLI generate when provenance fails.
	 */
	public const REASON_PROVENANCE_WRITE_FAILED = 'provenance_write_failed';

	/**
	 * Partial reason: alt and provenance both landed; only the optional long
	 * description failed → nothing is missing from history (BR-08).
	 * REST-only today (CLI generate does not write long description).
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
		self::PROVENANCE_HEALED,
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
		self::PROVENANCE_HEALED,
		self::PARTIAL,
		self::FAILED,
	);

	/**
	 * Statuses CLI generate may put on each row's `status`.
	 * Force-overwrite success emits {@see self::FORCED_OVERWRITE} (aligned with
	 * REST). {@see self::PROVENANCE_HEALED} is emitted when force=false and the
	 * stored alt already matched the draft (provenance gap heal). {@see self::DRY_RUN}
	 * is CLI-only.
	 *
	 * @var list<string>
	 */
	public const CLI_STATUSES = array(
		self::WRITTEN,
		self::SKIPPED_EXISTING_ALT,
		self::SKIPPED_EMPTY_ALT_TEXT,
		self::FORCED_OVERWRITE,
		self::PROVENANCE_HEALED,
		self::PARTIAL,
		self::FAILED,
		self::DRY_RUN,
	);

	/**
	 * Values for the `reason` field when status is partial.
	 * - {@see self::REASON_PROVENANCE_WRITE_FAILED}: REST describe + CLI generate.
	 * - {@see self::REASON_DESCRIPTION_WRITE_FAILED}: REST-only (long description).
	 *
	 * REASON_PROVENANCE_WRITE_FAILED covers two shapes and does NOT imply a
	 * recovery marker [R20-BR-30]:
	 * 1. Full provenance write failed after the alt landed — a verified
	 *    `_acx_description_provenance_pending` marker was planted (retryable gap).
	 * 2. Draft-key heal failure on already-present array provenance
	 *    (identity_complete / force no-op arms) — no marker planted; history
	 *    already lists the row via its provenance array.
	 * Consumers distinguish by reading the pending key and/or whether provenance
	 * is already an array.
	 *
	 * @var list<string>
	 */
	public const PARTIAL_REASONS = array(
		self::REASON_PROVENANCE_WRITE_FAILED,
		self::REASON_DESCRIPTION_WRITE_FAILED,
	);

	/**
	 * Bulk apply response bucket keys (ordered). Wire names are a stable SPA
	 * contract — values are media_id lists, not status strings. Do not rename.
	 *
	 * Governs `array_fill_keys` initialisation and envelope key order only.
	 * Outcome routing in the apply loop still uses hardcoded string literals
	 * that must stay byte-identical to these members; this const is not the
	 * single source for that routing.
	 *
	 * Correspondence to per-item {@see self} outcomes the apply loop produces:
	 * - applied          ← full success (alt + provenance verified); single-item
	 *                      analogues: WRITTEN / FORCED_OVERWRITE
	 * - partial          ← PARTIAL (alt landed, provenance did not; marker verified)
	 * - skipped_existing ← SKIPPED_EXISTING_ALT (guard / CAS abort)
	 * - skipped_no_draft ← empty draft (single-item: SKIPPED_EMPTY_ALT_TEXT)
	 * - skipped_invalid  ← non-attachment media_id (bulk-only; no single-item status)
	 * - failed           ← FAILED (alt write fail, or marker plant unverified)
	 *
	 * @var list<string>
	 */
	public const BULK_APPLY_BUCKETS = array(
		'applied',
		'partial',
		'skipped_existing',
		'skipped_no_draft',
		'skipped_invalid',
		'failed',
	);

	/**
	 * Non-bulk owner for `_acx_description_provenance_pending.run_id` written by
	 * CLI generate. Wire value is durable recovery evidence — do not rename.
	 * Bulk apply uses a real run UUID, not this sentinel [R20-BR-16].
	 */
	public const MARKER_OWNER_CLI = 'cli';

	/**
	 * Non-bulk owner for `_acx_description_provenance_pending.run_id` written by
	 * REST single-image describe. Wire value is durable recovery evidence — do
	 * not rename. Bulk apply uses a real run UUID, not this sentinel [R20-BR-16].
	 */
	public const MARKER_OWNER_SINGLE_IMAGE = 'single_image';

	/**
	 * All non-bulk provenance-pending marker owner sentinels.
	 *
	 * Membership distinguishes bulk from non-bulk: if `run_id` is in this set
	 * it is a fixed non-bulk owner; otherwise treat it as a bulk (or other)
	 * run id. Bulk UUIDs are intentionally absent [R20-BR-16].
	 *
	 * @var list<string>
	 */
	public const MARKER_OWNERS = array(
		self::MARKER_OWNER_CLI,
		self::MARKER_OWNER_SINGLE_IMAGE,
	);

	private function __construct() {}
}
