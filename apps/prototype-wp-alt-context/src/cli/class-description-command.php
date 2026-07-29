<?php

declare(strict_types=1);

namespace AltContext\Cli;

use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescribeMediaService;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function class_exists;
use function count;
use function get_post_meta;
use function gmdate;
use function in_array;
use function is_numeric;
use function is_wp_error;
use function sprintf;
use function trim;
use function update_post_meta;
use function wp_json_encode;

class DescriptionCommand extends \WP_CLI_Command {
	private DescriptionCandidateService $candidate_service;
	private DescribeMediaService $describe_service;

	public function __construct( ?DescriptionCandidateService $candidate_service = null, ?DescribeMediaService $describe_service = null ) {
		$this->candidate_service = $candidate_service ?? new DescriptionCandidateService();
		$this->describe_service  = $describe_service ?? new DescribeMediaService( new DescribeController() );
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
			$this->generate( $assoc_args );
			return;
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
			)['candidates']
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
	 * @param array<string,mixed> $assoc_args
	 */
	private function generate( array $assoc_args ): void {
		$format   = $this->parse_format( $assoc_args['format'] ?? 'table' );
		$media_id = $this->parse_optional_media_id( $assoc_args['media-id'] ?? null );
		$write    = $this->truthy_flag( $assoc_args['write'] ?? false );
		$force    = $this->truthy_flag( $assoc_args['force'] ?? false );

		$media_ids = array();
		if ( null !== $media_id ) {
			$media_ids[] = $media_id;
		} else {
			if ( ! isset( $assoc_args['limit'] ) ) {
				\WP_CLI::error( 'Pass --media-id or --limit for bounded generation.' );
			}

			foreach ( $this->candidate_service->list_missing_alt_candidates( $this->parse_limit( $assoc_args['limit'] ), 0 )['candidates'] as $row ) {
				$media_ids[] = (int) $row['media_id'];
			}
		}

		$rows = array();
		foreach ( $media_ids as $id ) {
			$rows[] = $this->generate_one( $id, $write, $force );
		}

		if ( 'json' === $format ) {
			\WP_CLI::log(
				(string) wp_json_encode(
					array(
						'command' => 'generate',
						'write'   => $write,
						'force'   => $force,
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
					'media_id=%d status=%s alt_text_draft=%s',
					(int) $row['media_id'],
					(string) $row['status'],
					(string) $row['alt_text_draft']
				)
			);
		}

		\WP_CLI::success( sprintf( 'Description generate rows: count=%d', count( $rows ) ) );
	}

	/**
	 * @return array<string,mixed>
	 */
	private function generate_one( int $media_id, bool $write, bool $force ): array {
		// The third constructor argument is route *attributes*, which
		// get_param() never reads; media_id must go through set_param().
		$request = new WP_REST_Request( 'POST', '/acx/v1/recognition/describe' );
		$request->set_param( 'media_id', $media_id );
		$result  = $this->describe_service->describe_media( $request );

		if ( is_wp_error( $result ) ) {
			return array(
				'media_id'       => $media_id,
				'status'         => 'failed',
				'alt_text_draft' => '',
				'error'          => $result->get_error_message(),
			);
		}

		$data = $result instanceof WP_REST_Response && is_array( $result->get_data() ) ? $result->get_data() : array();
		if ( $result instanceof WP_REST_Response && $result->get_status() >= 400 ) {
			return array(
				'media_id'       => $media_id,
				'status'         => 'failed',
				'alt_text_draft' => '',
				'error'          => (string) ( $data['message'] ?? $data['detail'] ?? 'Describe request failed.' ),
			);
		}

		// BR-116: same normaliser as REST write policy — non-string → '' (skip),
		// not (string) cast which would turn 42 into '42' while REST stored ''.
		$alt_text_draft = DescribeMediaService::normalize_alt_text_draft( $data['alt_text_draft'] ?? null );

		if ( ! $write ) {
			return array(
				'media_id'       => $media_id,
				'status'         => 'dry_run',
				'alt_text_draft' => $alt_text_draft,
			);
		}

		$existing_alt = trim( (string) get_post_meta( $media_id, '_wp_attachment_image_alt', true ) );
		if ( '' !== $existing_alt && ! $force ) {
			return array(
				'media_id'       => $media_id,
				'status'         => 'skipped_existing_alt',
				'alt_text_draft' => $alt_text_draft,
			);
		}

		if ( '' === $alt_text_draft ) {
			return array(
				'media_id'       => $media_id,
				'status'         => 'skipped_empty_alt_text',
				'alt_text_draft' => '',
			);
		}

		update_post_meta( $media_id, '_wp_attachment_image_alt', $alt_text_draft );
		// Stamp the exact string just written so history can resolve Generated-alt.
		update_post_meta( $media_id, '_acx_description_provenance', $this->build_provenance( $media_id, $data, $alt_text_draft ) );

		return array(
			'media_id'       => $media_id,
			'status'         => 'written',
			'alt_text_draft' => $alt_text_draft,
		);
	}

	/**
	 * Build the CLI provenance envelope for a generate-and-write.
	 *
	 * `$alt_text_draft` is the exact string just written to
	 * `_wp_attachment_image_alt` — only called on the write path (never on
	 * dry_run / skipped_existing_alt / skipped_empty_alt_text) so a draft that
	 * was never persisted is never recorded as if it were [rg-015].
	 *
	 * @param array<string,mixed> $data
	 * @param string              $alt_text_draft Exact draft written to alt meta.
	 * @return array<string,mixed>
	 */
	private function build_provenance( int $media_id, array $data, string $alt_text_draft ): array {
		return array(
			'source'                 => 'cli',
			'media_id'               => $media_id,
			'generated_at'           => gmdate( 'c' ),
			'adapter'                => (string) ( $data['adapter'] ?? '' ),
			'model_id'               => (string) ( $data['model_id'] ?? '' ),
			'model_version'          => (string) ( $data['model_version'] ?? '' ),
			'prompt_or_task_version' => (string) ( $data['prompt_or_task_version'] ?? '' ),
			// Exact string written to alt — history's Generated-alt column source.
			'alt_text_draft'         => $alt_text_draft,
		);
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

	/**
	 * @param mixed $value
	 */
	private function truthy_flag( $value ): bool {
		if ( true === $value ) {
			return true;
		}

		return in_array( (string) $value, array( '1', 'true', 'yes', 'on' ), true );
	}
}
