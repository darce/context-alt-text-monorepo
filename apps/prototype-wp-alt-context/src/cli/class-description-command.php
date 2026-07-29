<?php

declare(strict_types=1);

namespace AltContext\Cli;

require_once __DIR__ . '/../api/class-alt-text-write-status.php';

use AltContext\Api\AltTextWriteStatus;
use AltContext\Api\DescribeController;
use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescribeMediaService;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_key_exists;
use function class_exists;
use function count;
use function get_post_meta;
use function gmdate;
use function implode;
use function in_array;
use function is_array;
use function is_numeric;
use function is_string;
use function is_wp_error;
use function sprintf;
use function trim;
use function update_post_meta;
use function wp_json_encode;
use function wp_unslash;

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

		// Tally before any format branch so JSON and table share one exit policy
		// and one set of counts [R18-BR-01] [R17-BR-02] [R17-BR-09].
		$total         = count( $rows );
		$status_counts = array();
		foreach ( AltTextWriteStatus::CLI_STATUSES as $status_key ) {
			$status_counts[ $status_key ] = 0;
		}
		foreach ( $rows as $row ) {
			$status = (string) ( $row['status'] ?? '' );
			if ( array_key_exists( $status, $status_counts ) ) {
				++$status_counts[ $status ];
			}
		}
		$failed  = $status_counts[ AltTextWriteStatus::FAILED ];
		$partial = $status_counts[ AltTextWriteStatus::PARTIAL ];

		$summary = $this->build_generate_summary( $total, $status_counts );

		if ( 'json' === $format ) {
			$envelope = array(
				'command' => 'generate',
				'write'   => $write,
				'force'   => $force,
				'count'   => $total,
				'failed'  => $failed,
				'partial' => $partial,
			);
			foreach ( AltTextWriteStatus::CLI_STATUSES as $status_key ) {
				// failed/partial already present as top-level keys; still emit
				// every CLI status that actually occurred for operator clarity.
				if ( AltTextWriteStatus::FAILED === $status_key || AltTextWriteStatus::PARTIAL === $status_key ) {
					continue;
				}
				if ( $status_counts[ $status_key ] > 0 ) {
					$envelope[ $status_key ] = $status_counts[ $status_key ];
				}
			}
			$envelope['rows'] = $rows;
			\WP_CLI::log( (string) wp_json_encode( $envelope ) );
		} else {
			foreach ( $rows as $row ) {
				$reason      = isset( $row['reason'] ) && is_string( $row['reason'] ) && '' !== $row['reason']
					? (string) $row['reason']
					: '';
				$reason_part = '' !== $reason ? sprintf( ' reason=%s', $reason ) : '';
				\WP_CLI::log(
					sprintf(
						'media_id=%d status=%s%s alt_text_draft=%s',
						(int) $row['media_id'],
						(string) $row['status'],
						$reason_part,
						(string) $row['alt_text_draft']
					)
				);
			}
		}

		// Non-zero whenever anything did not fully land. Empty batch (count=0)
		// stays exit-0 — nothing-to-do is not failure [R18-BR-01] [R17-BR-02].
		if ( $total > 0 && ( $failed > 0 || $partial > 0 ) ) {
			\WP_CLI::error( $summary );
		}

		\WP_CLI::success( $summary );
	}

	/**
	 * Operator-facing summary: always count/failed/partial, plus every other
	 * CLI status that actually occurred [R17-BR-09] [rg-015].
	 *
	 * @param array<string,int> $status_counts
	 */
	private function build_generate_summary( int $total, array $status_counts ): string {
		$parts = array(
			sprintf( 'count=%d', $total ),
			sprintf( 'failed=%d', $status_counts[ AltTextWriteStatus::FAILED ] ?? 0 ),
			sprintf( 'partial=%d', $status_counts[ AltTextWriteStatus::PARTIAL ] ?? 0 ),
		);
		foreach ( AltTextWriteStatus::CLI_STATUSES as $status_key ) {
			if ( AltTextWriteStatus::FAILED === $status_key || AltTextWriteStatus::PARTIAL === $status_key ) {
				continue;
			}
			$count = $status_counts[ $status_key ] ?? 0;
			if ( $count > 0 ) {
				$parts[] = sprintf( '%s=%d', $status_key, $count );
			}
		}

		return 'Description generate rows: ' . implode( ' ', $parts );
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
				'status'         => AltTextWriteStatus::FAILED,
				'alt_text_draft' => '',
				'error'          => $result->get_error_message(),
			);
		}

		$data = $result instanceof WP_REST_Response && is_array( $result->get_data() ) ? $result->get_data() : array();
		if ( $result instanceof WP_REST_Response && $result->get_status() >= 400 ) {
			return array(
				'media_id'       => $media_id,
				'status'         => AltTextWriteStatus::FAILED,
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
				'status'         => AltTextWriteStatus::DRY_RUN,
				'alt_text_draft' => $alt_text_draft,
			);
		}

		$existing_alt = trim( (string) get_post_meta( $media_id, '_wp_attachment_image_alt', true ) );
		if ( '' !== $existing_alt && ! $force ) {
			return array(
				'media_id'       => $media_id,
				'status'         => AltTextWriteStatus::SKIPPED_EXISTING_ALT,
				'alt_text_draft' => $alt_text_draft,
			);
		}

		if ( '' === $alt_text_draft ) {
			return array(
				'media_id'       => $media_id,
				'status'         => AltTextWriteStatus::SKIPPED_EMPTY_ALT_TEXT,
				'alt_text_draft' => '',
			);
		}

		// S3-02 / BR-01: honor update_post_meta() returns. No-op (false when the
		// stored value already equals what WP will store after unslash) is success
		// via read-back; a real alt failure must not stamp provenance claiming a
		// draft that never landed. Status vocabulary matches bulk apply:
		// written (full success), partial (alt ok, provenance not), failed.
		// Compare against wp_unslash( $draft ) — update_metadata() unslashes before
		// store/equality (BR-17). [rg-015]
		// Deliberate path divergence: CLI force-overwrite success emits WRITTEN,
		// not FORCED_OVERWRITE (REST-only). Leave that as-is this wave.
		$expected_alt = wp_unslash( $alt_text_draft );
		$alt_written  = update_post_meta( $media_id, '_wp_attachment_image_alt', $alt_text_draft );
		if ( false === $alt_written ) {
			$current = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
			if ( ! is_string( $current ) || $expected_alt !== $current ) {
				return array(
					'media_id'       => $media_id,
					'status'         => AltTextWriteStatus::FAILED,
					'alt_text_draft' => $alt_text_draft,
				);
			}
		}

		// Stamp provenance only after a verified alt write so history never lists
		// a Generated-alt for a draft that did not land [rg-015].
		$provenance           = $this->build_provenance( $media_id, $data, $alt_text_draft );
		$expected_provenance  = wp_unslash( $provenance );
		$prov_written         = update_post_meta( $media_id, '_acx_description_provenance', $provenance );
		if ( false === $prov_written ) {
			$current_prov = get_post_meta( $media_id, '_acx_description_provenance', true );
			$prov_ok      = is_array( $current_prov ) && $expected_provenance === $current_prov;
			if ( ! $prov_ok ) {
				// Alt landed; provenance did not. CLI generate does not write
				// long description, so the only partial cause is provenance
				// stamp failure — carry the same REASON_* as REST [R17-BR-06].
				return array(
					'media_id'       => $media_id,
					'status'         => AltTextWriteStatus::PARTIAL,
					'reason'         => AltTextWriteStatus::REASON_PROVENANCE_WRITE_FAILED,
					'alt_text_draft' => $alt_text_draft,
				);
			}
		}

		return array(
			'media_id'       => $media_id,
			'status'         => AltTextWriteStatus::WRITTEN,
			'alt_text_draft' => $alt_text_draft,
		);
	}

	/**
	 * Build the CLI provenance envelope for a generate-and-write.
	 *
	 * Called only after a verified alt write (or accepted no-op read-back). Never
	 * on dry_run / skipped_existing_alt / skipped_empty_alt_text / alt-write
	 * failure — a draft that was never persisted is never recorded as if it were
	 * [rg-015]. Status of the caller is `written` only when both alt and
	 * provenance are verified; provenance failure surfaces as `partial`.
	 *
	 * @param array<string,mixed> $data
	 * @param string              $alt_text_draft Draft written (or already stored) to alt meta.
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
