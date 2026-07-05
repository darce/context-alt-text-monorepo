<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function array_reverse;
use function array_slice;
use function array_values;
use function count;
use function gmdate;
use function is_array;

/**
 * Stores description usage/error events.
 *
 * E20-7 keeps this repository intentionally narrow and array-backed so the
 * budget service contract can be exercised before the durable storage shape is
 * expanded by provider-cost work.
 */
class DescriptionUsageRepository {
	/**
	 * @param array<string,mixed> $row
	 * @return array<string,mixed>
	 */
	public function insert( array $row ): array {
		if ( ! isset( $GLOBALS['__ac_description_usage_rows'] ) || ! is_array( $GLOBALS['__ac_description_usage_rows'] ) ) {
			$GLOBALS['__ac_description_usage_rows'] = array();
		}

		$row = array_merge(
			array(
				'id'                  => count( $GLOBALS['__ac_description_usage_rows'] ) + 1,
				'occurred_at'         => gmdate( 'c' ),
				'media_id'            => 0,
				'outcome'             => 'success',
				'adapter'             => '',
				'provider'            => '',
				'duration_ms'         => null,
				'cached'              => false,
				'write_status'        => null,
				'cost_amount'         => 0.0,
				'cost_currency'       => null,
				'error_code'          => null,
				'error_message'       => null,
				'retryable'           => null,
				'source'              => null,
			),
			$row
		);

		$GLOBALS['__ac_description_usage_rows'][] = $row;

		return $row;
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function all(): array {
		if ( ! isset( $GLOBALS['__ac_description_usage_rows'] ) || ! is_array( $GLOBALS['__ac_description_usage_rows'] ) ) {
			return array();
		}

		return array_values( $GLOBALS['__ac_description_usage_rows'] );
	}

	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function recent_errors( int $limit = 10 ): array {
		$errors = array();
		foreach ( $this->all() as $row ) {
			if ( 'failure' === ( $row['outcome'] ?? null ) ) {
				$errors[] = $row;
			}
		}

		return array_slice( array_reverse( $errors ), 0, $limit );
	}
}
