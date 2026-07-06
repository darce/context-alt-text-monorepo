<?php

declare(strict_types=1);

namespace AltContext\Cli;

use AltContext\Api\Services\DescriptionContentRefreshService;

use function absint;
use function array_unique;
use function array_values;
use function class_exists;
use function count;
use function in_array;
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

		$limit  = $this->normalize_limit( $assoc_args['limit'] ?? null );
		$apply  = $this->normalize_bool( $assoc_args['apply'] ?? false );
		$result = $apply ? $this->service->apply( $media_ids, $limit ) : $this->service->dry_run( $media_ids, $limit );
		$summary = is_array( $result['summary'] ?? null ) ? $result['summary'] : array();

		\WP_CLI::success(
			sprintf(
				'Description refresh complete. dry_run=%d candidates=%d changed=%d skipped=%d',
				$apply ? 0 : 1,
				(int) ( $summary['candidates'] ?? 0 ),
				(int) ( $summary['changed'] ?? 0 ),
				(int) ( $summary['skipped'] ?? 0 )
			)
		);
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
