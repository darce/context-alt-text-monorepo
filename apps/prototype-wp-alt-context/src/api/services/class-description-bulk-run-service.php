<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\Repositories\DescriptionRunRepository;
use RuntimeException;

use function array_slice;
use function array_values;
use function count;
use function is_callable;
use function is_string;
use function max;
use function trim;
use function wp_generate_uuid4;

class DescriptionBulkRunService {
	private DescriptionRunRepository $repository;

	/**
	 * @var callable(int):array<string,mixed>
	 */
	private $generator;

	/**
	 * @param callable(int):array<string,mixed>|null $generator
	 */
	public function __construct( ?DescriptionRunRepository $repository = null, ?callable $generator = null ) {
		$this->repository = $repository ?? new DescriptionRunRepository();
		$this->generator  = is_callable( $generator )
			? $generator
			: static fn (int $media_id): array => array(
				'status'        => 'skipped',
				'error_code'    => 'generator_unavailable',
				'error_message' => 'No description generator was configured.',
			);
	}

	/**
	 * @param int[] $candidate_media_ids
	 * @return array<string,mixed>
	 */
	public function run( array $candidate_media_ids, int $limit, int $batch_size, ?string $run_id = null ): array {
		$this->assert_bounds( $limit, $batch_size );

		$bounded_ids = array_values( array_slice( $candidate_media_ids, 0, $limit ) );
		$normalized_run_id = $this->normalize_run_id( $run_id );
		$this->repository->create_run( $normalized_run_id, $bounded_ids, $limit, $batch_size );

		foreach ( array_chunk( $bounded_ids, max( 1, $batch_size ) ) as $batch ) {
			foreach ( $batch as $media_id ) {
				$this->process_item( $normalized_run_id, (int) $media_id );
			}
		}

		return $this->repository->get_run_status( $normalized_run_id );
	}

	/**
	 * @return array<string,mixed>
	 */
	public function retry( string $run_id ): array {
		$normalized_run_id = trim( $run_id );
		foreach ( $this->repository->list_retryable_items( $normalized_run_id ) as $item ) {
			$this->process_item( $normalized_run_id, (int) $item['media_id'] );
		}

		return $this->repository->get_run_status( $normalized_run_id );
	}

	private function process_item( string $run_id, int $media_id ): void {
		$this->repository->update_item_status( $run_id, $media_id, 'running' );
		$result = ( $this->generator )( $media_id );

		$status = is_string( $result['status'] ?? null ) ? (string) $result['status'] : 'failed';
		$this->repository->update_item_status(
			$run_id,
			$media_id,
			$status,
			is_string( $result['error_code'] ?? null ) ? (string) $result['error_code'] : '',
			is_string( $result['error_message'] ?? null ) ? (string) $result['error_message'] : ''
		);
	}

	private function assert_bounds( int $limit, int $batch_size ): void {
		if ( $limit < 1 || $batch_size < 1 ) {
			throw new RuntimeException( 'Bulk description runs require limit and batch_size of at least 1.' );
		}
	}

	private function normalize_run_id( ?string $run_id ): string {
		$normalized = trim( (string) $run_id );
		if ( '' !== $normalized ) {
			return $normalized;
		}

		return wp_generate_uuid4();
	}
}
