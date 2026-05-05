<?php

declare(strict_types=1);

namespace AltContext\Cli;

/**
 * Inspect the local identity-member mirror for split cluster assignments.
 *
 * @package AltContext\Cli
 */
class MirrorIntegrityCommand extends \WP_CLI_Command {

	private const DEFAULT_THRESHOLD = 0.999;
	private const DEFAULT_LIMIT = 20;

	/**
	 * Report suspicious mirror rows where one attachment appears in multiple clusters.
	 *
	 * Flags attachments whose local mirror rows still contain more than one
	 * distinct cluster UUID at or above the requested similarity threshold.
	 * Operators should clear these anomalies before trusting the local mirror as
	 * a faithful projection of backend identity membership.
	 *
	 * ## OPTIONS
	 *
	 * [--threshold=<similarity>]
	 * : Minimum similarity to inspect. Defaults to 0.999.
	 *
	 * [--limit=<count>]
	 * : Maximum number of suspicious attachments to report. Defaults to 20.
	 *
	 * [--format=<format>]
	 * : Output format: `table` or `json`. Defaults to `table`.
	 *
	 * [--attachment-id=<id>]
	 * : Restrict the report to one attachment ID.
	 *
	 * ## EXAMPLES
	 *
	 *     wp acx mirror-integrity
	 *     wp acx mirror-integrity --threshold=0.999 --limit=50 --format=json
	 *
	 * @param string[] $args
	 * @param array<string,mixed> $assoc_args
	 */
	public function __invoke( array $args, array $assoc_args ): void {
		if ( ! \class_exists( '\\WP_CLI' ) ) {
			return;
		}

		/** @var \wpdb $wpdb */
		global $wpdb;

		if ( ! isset( $wpdb ) || ! \is_object( $wpdb ) || ! \method_exists( $wpdb, 'get_results' ) || ! \method_exists( $wpdb, 'prepare' ) ) {
			\WP_CLI::error( '$wpdb is not available.' );
		}

		$threshold = $this->parse_threshold( $assoc_args['threshold'] ?? self::DEFAULT_THRESHOLD );
		$limit     = $this->parse_limit( $assoc_args['limit'] ?? self::DEFAULT_LIMIT );
		$format    = $this->parse_format( $assoc_args['format'] ?? 'table' );
		$attachment_id = $this->parse_attachment_id( $assoc_args['attachment-id'] ?? null );

		$table_name = $wpdb->prefix . 'acx_identity_members';
		$query_template =
			'SELECT attachment_id, COUNT(DISTINCT cluster_uuid) AS distinct_cluster_count, ' .
			'MAX(updated_at) AS last_seen_at, ' .
			'GROUP_CONCAT(DISTINCT cluster_uuid ORDER BY cluster_uuid SEPARATOR ",") AS cluster_uuids ' .
			'FROM %i ' .
			'WHERE attachment_id IS NOT NULL AND similarity IS NOT NULL AND similarity >= %f ';

		if ( null !== $attachment_id ) {
			$query_template .= 'AND attachment_id = %d ';
		}

		$query_template .=
			'GROUP BY attachment_id ' .
			'HAVING COUNT(DISTINCT cluster_uuid) > 1 ' .
			'ORDER BY distinct_cluster_count DESC, attachment_id DESC ' .
			'LIMIT %d';

		$query_args = array( $table_name, $threshold );
		if ( null !== $attachment_id ) {
			$query_args[] = $attachment_id;
		}
		$query_args[] = $limit;

		$query = $wpdb->prepare( $query_template, ...$query_args );

		$rows = $wpdb->get_results( $query, ARRAY_A );
		if ( ! \is_array( $rows ) ) {
			$rows = array();
		}

		$report = \array_map( array( $this, 'normalize_row' ), $rows );

		if ( 'json' === $format ) {
			$payload = array(
				'threshold' => $threshold,
				'limit'     => $limit,
				'count'     => \count( $report ),
				'rows'      => $report,
			);

			if ( null !== $attachment_id ) {
				$payload['attachment_id'] = $attachment_id;
			}

			\WP_CLI::log(
				(string) \wp_json_encode( $payload )
			);

			return;
		}

		if ( array() === $report ) {
			\WP_CLI::success(
				\sprintf(
					null !== $attachment_id
						? 'No suspicious mirror assignments found for attachment %d at similarity >= %s.'
						: 'No suspicious mirror assignments found at similarity >= %s.',
					null !== $attachment_id ? $attachment_id : $this->format_threshold( $threshold ),
					$this->format_threshold( $threshold )
				)
			);

			return;
		}

		\WP_CLI::log(
			\sprintf(
				null !== $attachment_id
					? 'Suspicious mirror assignments for attachment %d at similarity >= %s:'
					: 'Suspicious mirror assignments at similarity >= %s:',
				null !== $attachment_id ? $attachment_id : $this->format_threshold( $threshold ),
				$this->format_threshold( $threshold )
			)
		);

		foreach ( $report as $row ) {
			\WP_CLI::log(
				\sprintf(
					'attachment_id=%d distinct_clusters=%d last_seen_at=%s cluster_uuids=%s',
					$row['attachment_id'],
					$row['distinct_cluster_count'],
					$row['last_seen_at'],
					\implode( ',', $row['cluster_uuids'] )
				)
			);
		}

		\WP_CLI::warning(
			\sprintf(
				'Found %d suspicious attachment(s). Investigate mirror drift before trusting the local projection.',
				\count( $report )
			)
		);
	}

	/**
	 * @param mixed $value
	 */
	private function parse_threshold( $value ): float {
		if ( ! \is_numeric( $value ) ) {
			\WP_CLI::error( 'Threshold must be numeric.' );
		}

		$threshold = (float) $value;
		if ( $threshold <= 0.0 || $threshold > 1.0 ) {
			\WP_CLI::error( 'Threshold must be greater than 0 and less than or equal to 1.' );
		}

		return $threshold;
	}

	/**
	 * @param mixed $value
	 */
	private function parse_limit( $value ): int {
		if ( ! \is_numeric( $value ) ) {
			\WP_CLI::error( 'Limit must be numeric.' );
		}

		$limit = \absint( $value );
		if ( $limit < 1 ) {
			\WP_CLI::error( 'Limit must be at least 1.' );
		}

		return $limit;
	}

	/**
	 * @param mixed $value
	 */
	private function parse_format( $value ): string {
		$format = (string) $value;
		if ( ! \in_array( $format, array( 'table', 'json' ), true ) ) {
			\WP_CLI::error( 'Format must be one of: table, json.' );
		}

		return $format;
	}

	/**
	 * @param mixed $value
	 */
	private function parse_attachment_id( $value ): ?int {
		if ( null === $value || '' === $value ) {
			return null;
		}

		if ( ! \is_numeric( $value ) ) {
			\WP_CLI::error( 'Attachment ID must be numeric.' );
		}

		$attachment_id = \absint( $value );
		if ( $attachment_id < 1 ) {
			\WP_CLI::error( 'Attachment ID must be at least 1.' );
		}

		return $attachment_id;
	}

	private function format_threshold( float $threshold ): string {
		return \rtrim( \rtrim( \number_format( $threshold, 6, '.', '' ), '0' ), '.' );
	}

	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	private function normalize_row( array $row ): array {
		$cluster_uuids = (string) ( $row['cluster_uuids'] ?? '' );

		return array(
			'attachment_id'           => (int) ( $row['attachment_id'] ?? 0 ),
			'distinct_cluster_count'  => (int) ( $row['distinct_cluster_count'] ?? 0 ),
			'last_seen_at'            => (string) ( $row['last_seen_at'] ?? '' ),
			'cluster_uuids'           => '' === $cluster_uuids ? array() : \explode( ',', $cluster_uuids ),
		);
	}
}
