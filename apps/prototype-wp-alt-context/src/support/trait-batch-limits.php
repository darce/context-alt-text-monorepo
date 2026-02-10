<?php
/**
 * Shared batch limit configuration.
 *
 * @package AltContext\Support
 */

declare(strict_types=1);

namespace AltContext\Support;

/**
 * Provides shared batch limit constants and methods.
 *
 * NOTE: Batch limits disabled for MVP. All tiers use the same limit.
 * TODO: Restore tier-based limits post-MVP.
 * See docs/tasks/4.0/4.11.0/stability-audit-2026-01-20.md
 */
trait BatchLimits {
	/**
	 * Recognized tiers for validation/normalization.
	 */
	private const ALLOWED_TIERS = array( 'free', 'pro', 'business', 'enterprise' );

	/**
	 * MVP batch limit (same for all tiers).
	 */
	private const MVP_BATCH_LIMIT = 10000;

	/**
	 * Get the batch limit for a specific tier.
	 *
	 * @param string $_tier The tier name (unused for MVP).
	 * @return int The batch limit.
	 */
	protected function get_tier_batch_limit_for( string $_tier ): int {
		unset( $_tier ); // MVP: tiered limits are intentionally disabled.
		// MVP: All tiers use the same limit.
		return self::MVP_BATCH_LIMIT;
	}

	/**
	 * Get the batch limit for the current site's tier.
	 *
	 * @return int The batch limit.
	 */
	protected function get_current_tier_batch_limit(): int {
		return self::MVP_BATCH_LIMIT;
	}

	/**
	 * Check whether a tier is recognized.
	 *
	 * @param string $tier Tier name.
	 * @return bool
	 */
	protected function is_valid_tier( string $tier ): bool {
		return in_array( $tier, self::ALLOWED_TIERS, true );
	}
}
