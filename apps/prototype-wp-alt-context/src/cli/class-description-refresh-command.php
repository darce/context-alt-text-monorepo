<?php

declare(strict_types=1);

namespace AltContext\Cli;

use AltContext\Api\Services\DescriptionContentRefreshService;

use function absint;
use function array_key_exists;
use function array_unique;
use function array_values;
use function class_exists;
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
	 * No changed/failed keys.
	 *
	 * @param array<string,mixed> $summary
	 */
	private function report_dry_run( array $summary ): void {
		\WP_CLI::success(
			sprintf(
				'Description refresh complete. dry_run=1 candidates=%d skipped=%d',
				(int) ( $summary['candidates'] ?? 0 ),
				(int) ( $summary['skipped'] ?? 0 )
			)
		);
	}

	/**
	 * apply summary: dry_run, scanned_posts, media_ids, candidates, changed, failed, skipped.
	 *
	 * @param array<string,mixed> $result
	 * @param array<string,mixed> $summary
	 */
	private function report_apply( array $result, array $summary ): void {
		// apply() always includes changed/failed; read them only when present.
		$changed = array_key_exists( 'changed', $summary ) ? (int) $summary['changed'] : null;
		$failed  = array_key_exists( 'failed', $summary ) ? (int) $summary['failed'] : null;

		$parts = array(
			'dry_run=0',
			'candidates=' . (int) ( $summary['candidates'] ?? 0 ),
		);
		if ( null !== $changed ) {
			$parts[] = 'changed=' . $changed;
		}
		if ( null !== $failed ) {
			$parts[] = 'failed=' . $failed;
		}
		$parts[] = 'skipped=' . (int) ( $summary['skipped'] ?? 0 );

		$message = 'Description refresh complete. ' . implode( ' ', $parts );

		$failed_rows = is_array( $result['failed'] ?? null ) ? $result['failed'] : array();
		foreach ( $failed_rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}
			\WP_CLI::log(
				sprintf(
					'failed post_id=%d media_id=%d reason=%s',
					(int) ( $row['post_id'] ?? 0 ),
					(int) ( $row['media_id'] ?? 0 ),
					(string) ( $row['reason'] ?? '' )
				)
			);
		}

		// Non-zero exit so scripted callers can distinguish failure from success [HAI-13].
		// Partial success (changed>0 && failed>0) is still a failure: some intended
		// writes did not land.
		if ( null !== $failed && $failed > 0 ) {
			\WP_CLI::error( $message );
		}

		\WP_CLI::success( $message );
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
