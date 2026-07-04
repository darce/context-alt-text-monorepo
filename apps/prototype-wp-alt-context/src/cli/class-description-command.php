<?php

declare(strict_types=1);

namespace AltContext\Cli;

use AltContext\Api\Services\DescriptionCandidateService;

use function absint;
use function class_exists;
use function count;
use function in_array;
use function is_numeric;
use function sprintf;
use function wp_json_encode;

class DescriptionCommand extends \WP_CLI_Command {
	private DescriptionCandidateService $candidate_service;

	public function __construct( ?DescriptionCandidateService $candidate_service = null ) {
		$this->candidate_service = $candidate_service ?? new DescriptionCandidateService();
	}

	/**
	 * Inspect or generate image descriptions.
	 *
	 * ## OPTIONS
	 *
	 * <status|generate>
	 * : Description operation to run.
	 *
	 * [--media-id=<id>]
	 * : Restrict the operation to one attachment.
	 *
	 * [--limit=<count>]
	 * : Maximum missing-alt candidates to inspect. Defaults to 50 and caps at 100.
	 *
	 * [--format=<format>]
	 * : Output format: `table` or `json`. Defaults to `table`.
	 *
	 * @param string[] $args
	 * @param array<string,mixed> $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! class_exists( '\\WP_CLI' ) ) {
			return;
		}

		$subcommand = (string) ( $args[0] ?? '' );
		if ( 'status' === $subcommand ) {
			$this->status( $assoc_args );
			return;
		}

		if ( 'generate' === $subcommand ) {
			\WP_CLI::error( 'Description generation is not available until the generate slice is enabled.' );
		}

		\WP_CLI::error( 'Usage: wp alt-context describe <status|generate>.' );
	}

	/**
	 * @param array<string,mixed> $assoc_args
	 */
	private function status( array $assoc_args ): void {
		$format   = $this->parse_format( $assoc_args['format'] ?? 'table' );
		$media_id = $this->parse_optional_media_id( $assoc_args['media-id'] ?? null );

		$rows = null === $media_id
			? $this->candidate_service->list_missing_alt_candidates(
				$this->parse_limit( $assoc_args['limit'] ?? 50 ),
				absint( $assoc_args['offset'] ?? 0 )
			)
			: $this->candidate_service->get_status_for_media_ids( array( $media_id ) );

		if ( 'json' === $format ) {
			\WP_CLI::log(
				(string) wp_json_encode(
					array(
						'command' => 'status',
						'count'   => count( $rows ),
						'rows'    => $rows,
					)
				)
			);
			return;
		}

		foreach ( $rows as $row ) {
			\WP_CLI::log(
				sprintf(
					'media_id=%d has_alt_text=%s candidate_reason=%s provenance=%s title=%s',
					(int) $row['media_id'],
					! empty( $row['has_alt_text'] ) ? 'yes' : 'no',
					(string) $row['candidate_reason'],
					null === $row['provenance'] ? 'none' : 'present',
					(string) $row['title']
				)
			);
		}

		\WP_CLI::success( sprintf( 'Description status rows: count=%d', count( $rows ) ) );
	}

	/**
	 * @param mixed $value
	 */
	private function parse_format( $value ): string {
		$format = (string) $value;
		if ( ! in_array( $format, array( 'table', 'json' ), true ) ) {
			\WP_CLI::error( 'Format must be one of: table, json.' );
		}

		return $format;
	}

	/**
	 * @param mixed $value
	 */
	private function parse_limit( $value ): int {
		if ( ! is_numeric( $value ) ) {
			\WP_CLI::error( 'Limit must be numeric.' );
		}

		$limit = absint( $value );
		if ( $limit < 1 ) {
			\WP_CLI::error( 'Limit must be at least 1.' );
		}

		return min( 100, $limit );
	}

	/**
	 * @param mixed $value
	 */
	private function parse_optional_media_id( $value ): ?int {
		if ( null === $value || '' === $value ) {
			return null;
		}
		if ( ! is_numeric( $value ) ) {
			\WP_CLI::error( 'Media ID must be numeric.' );
		}

		$media_id = absint( $value );
		if ( $media_id < 1 ) {
			\WP_CLI::error( 'Media ID must be at least 1.' );
		}

		return $media_id;
	}
}
