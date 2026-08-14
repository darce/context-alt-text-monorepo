<?php

declare(strict_types=1);

namespace AltContext\Cli;

use AltContext\Api\Services\DescriptionContentRefreshService;

use function absint;
use function array_key_exists;
use function array_unique;
use function array_values;
use function class_exists;
use function count;
use function implode;
use function in_array;
use function is_array;
use function is_numeric;
use function sprintf;

class DescriptionRefreshCommand extends \WP_CLI_Command {
	private DescriptionContentRefreshService $service;

	public function __construct( ?DescriptionContentRefreshService $service = null ) {
		$this->service = $service ?? new DescriptionContentRefreshService();
	}

	/**
	 * Refresh embedded post/page image alt text from Media Library attachment alt text.
	 *
	 * ## OPTIONS
	 *
	 * <media-id>...
	 * : One or more attachment IDs whose current alt text should be propagated.
	 *
	 * [--apply]
	 * : Apply safe updates. Omit for dry-run.
	 *
	 * [--limit=<number>]
	 * : Maximum posts/pages/products to scan.
	 *
	 * @param string[] $args
	 * @param array<string,mixed> $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! class_exists( '\\WP_CLI' ) ) {
			return;
		}

		$media_ids = $this->normalize_media_ids( $args );
		if ( empty( $media_ids ) ) {
			\WP_CLI::error( 'No media IDs provided. Pass one or more attachment IDs.' );
		}

		$limit   = $this->normalize_limit( $assoc_args['limit'] ?? null );
		$apply   = $this->normalize_bool( $assoc_args['apply'] ?? false );
		$result  = $apply ? $this->service->apply( $media_ids, $limit ) : $this->service->dry_run( $media_ids, $limit );
		$summary = is_array( $result['summary'] ?? null ) ? $result['summary'] : array();

		// dry_run() and apply() return different summary shapes — format each
		// path explicitly so a missing key is never fabricated as 0 [rg-015].
		if ( $apply ) {
			$this->report_apply( $result, $summary );
			return;
		}

		$this->report_dry_run( $summary );
	}

	/**
	 * dry_run summary: dry_run, scanned_posts, media_ids, candidates, skipped.
	 * No changed/failed keys. Emit candidates/skipped only when present —
	 * never fabricate a zero for an absent key [rg-015].
	 *
	 * @param array<string,mixed> $summary
	 */
	private function report_dry_run( array $summary ): void {
		$parts = array( 'dry_run=1' );
		if ( array_key_exists( 'candidates', $summary ) ) {
			$parts[] = 'candidates=' . (int) $summary['candidates'];
		}
		if ( array_key_exists( 'skipped', $summary ) ) {
			$parts[] = 'skipped=' . (int) $summary['skipped'];
		}

		\WP_CLI::success( 'Description refresh complete. ' . implode( ' ', $parts ) );
	}

	/**
	 * apply summary: dry_run, scanned_posts, media_ids, candidates, changed, failed, skipped.
	 *
	 * Summary counters must agree with their row arrays. A mismatch is a
	 * producer integrity error — exit non-zero rather than paper over with
	 * max() or either side alone [R20-BR-02] [R20-BR-07].
	 *
	 * @param array<string,mixed> $result
	 * @param array<string,mixed> $summary
	 */
	private function report_apply( array $result, array $summary ): void {
		// apply() always includes changed/failed/skipped; read them only when
		// present. Never fabricate a zero for an absent key [rg-015] [R18-BR-03].
		$changed = array_key_exists( 'changed', $summary ) ? (int) $summary['changed'] : null;
		$failed  = array_key_exists( 'failed', $summary ) ? (int) $summary['failed'] : null;
		$skipped = array_key_exists( 'skipped', $summary ) ? (int) $summary['skipped'] : null;

		$changed_row_count = $this->count_result_rows( $result['changed'] ?? null );
		$skipped_row_count = $this->count_result_rows( $result['skipped'] ?? null );

		$failed_rows      = is_array( $result['failed'] ?? null ) ? $result['failed'] : array();
		$failed_row_count = 0;
		foreach ( $failed_rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}
			++$failed_row_count;
			\WP_CLI::log(
				sprintf(
					'failed post_id=%d media_id=%d reason=%s',
					(int) ( $row['post_id'] ?? 0 ),
					(int) ( $row['media_id'] ?? 0 ),
					(string) ( $row['reason'] ?? '' )
				)
			);
		}

		// Disagreement between a present summary counter and its row array is
		// not resolvable at the CLI — surface integrity error [R20-BR-07].
		$changed_mismatch = null !== $changed && $changed !== $changed_row_count;
		$failed_mismatch  = null !== $failed && $failed !== $failed_row_count;
		$skipped_mismatch = null !== $skipped && $skipped !== $skipped_row_count;
		$count_mismatch   = $changed_mismatch || $failed_mismatch || $skipped_mismatch;

		// Never fabricate candidates=0 for an absent key [R20-BR-03] [rg-015].
		$parts = array( 'dry_run=0' );
		if ( array_key_exists( 'candidates', $summary ) ) {
			$parts[] = 'candidates=' . (int) $summary['candidates'];
		}
		// Emit counter tokens only when present and consistent with rows —
		// a mismatched number is not printed as authoritative [R20-BR-02].
		if ( null !== $changed && ! $changed_mismatch ) {
			$parts[] = 'changed=' . $changed;
		}
		if ( null !== $failed && ! $failed_mismatch ) {
			$parts[] = 'failed=' . $failed;
		}
		if ( null !== $skipped && ! $skipped_mismatch ) {
			$parts[] = 'skipped=' . $skipped;
		}

		$counts = implode( ' ', $parts );

		// Exit ORs summary failed (when present) with logged-row evidence so a
		// under-reporting summary still exits non-zero [R17-BR-04] [rg-015] [HAI-13].
		// Absent `failed` key is an integrity error (absence ≠ success).
		// Counter/row mismatch is also an integrity error [R20-BR-07].
		$has_failures    = ( null !== $failed && $failed > 0 ) || $failed_row_count > 0;
		$missing_failed  = null === $failed;
		$integrity_error = $missing_failed || $count_mismatch;

		if ( $has_failures || $integrity_error ) {
			// Leading sentence matches outcome — do not claim "complete" on failure
			// [R17-BR-11].
			if ( $count_mismatch ) {
				$message = 'Description refresh incomplete (summary count mismatch). ' . $counts;
			} elseif ( $integrity_error && ! $has_failures ) {
				$message = 'Description refresh incomplete (summary missing failed count). ' . $counts;
			} else {
				$message = 'Description refresh failed. ' . $counts;
			}
			\WP_CLI::error( $message );
		}

		\WP_CLI::success( 'Description refresh complete. ' . $counts );
	}

	/**
	 * Count array-shaped rows in a result list (non-arrays ignored).
	 *
	 * @param mixed $rows
	 */
	private function count_result_rows( $rows ): int {
		if ( ! is_array( $rows ) ) {
			return 0;
		}

		$count = 0;
		foreach ( $rows as $row ) {
			if ( is_array( $row ) ) {
				++$count;
			}
		}

		return $count;
	}

	/**
	 * @param string[] $args
	 * @return int[]
	 */
	private function normalize_media_ids( array $args ): array {
		$media_ids = array();
		foreach ( $args as $arg ) {
			if ( ! is_numeric( $arg ) ) {
				continue;
			}

			$media_id = absint( $arg );
			if ( $media_id > 0 ) {
				$media_ids[] = $media_id;
			}
		}

		return array_values( array_unique( $media_ids ) );
	}

	/**
	 * @param mixed $value
	 */
	private function normalize_limit( $value ): int {
		$limit = absint( $value );
		return $limit > 0 ? $limit : 50;
	}

	/**
	 * @param mixed $value
	 */
	private function normalize_bool( $value ): bool {
		if ( true === $value ) {
			return true;
		}

		return in_array( (string) $value, array( '1', 'true', 'yes', 'on' ), true );
	}
}
