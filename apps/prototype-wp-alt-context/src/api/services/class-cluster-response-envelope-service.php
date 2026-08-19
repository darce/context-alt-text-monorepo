<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

use AltContext\Sovereign\Mappers\ClusterResponseMapper;
use WP_Error;
use WP_REST_Response;

use function count;
use function is_array;
use function is_bool;
use function is_numeric;
use function max;

class ClusterResponseEnvelopeService {
	private ClusterResponseMapper $cluster_mapper;

	public function __construct( ?ClusterResponseMapper $cluster_mapper = null ) {
		$this->cluster_mapper = $cluster_mapper ?? new ClusterResponseMapper();
	}

	/**
	 * @param array<int,array<string,mixed>> $rows
	 * @param array<int,array<string,mixed>> $clusters
	 * @return array<string,mixed>
	 */
	public function build_cluster_list_envelope( array $rows, array $clusters, int $limit ): array {
		$total = count( $clusters );

		if ( isset( $rows[0]['total_count'] ) && is_numeric( $rows[0]['total_count'] ) ) {
			$total = max( 0, (int) $rows[0]['total_count'] );
		}

		return array(
			'clusters' => $clusters,
			'limit' => $limit,
			'total' => $total,
			'truncated' => $total > count( $clusters ),
		);
	}

	/**
	 * @param array<int,array<string,mixed>> $members
	 * @return array<string,mixed>
	 */
	public function build_cluster_members_envelope( array $members, int $limit, int $total, int $offset = 0 ): array {
		$offset = max( 0, $offset );
		return array(
			'members' => $members,
			'limit' => $limit,
			'total' => $total,
			'truncated' => ( $offset + count( $members ) ) < $total,
		);
	}

	/**
	 * @param array<int,string> $labels
	 * @return array<string,mixed>
	 */
	public function build_cluster_labels_envelope( array $labels, int $limit, int $total ): array {
		return array(
			'labels' => $labels,
			'limit' => $limit,
			'total' => $total,
			'truncated' => $total > count( $labels ),
		);
	}

	public function normalize_cluster_list_response( WP_REST_Response|WP_Error $response, int $requested_limit ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		if ( isset( $data['clusters'] ) && is_array( $data['clusters'] ) ) {
			if ( ! isset( $data['limit'], $data['total'], $data['truncated'] ) || ! is_numeric( $data['limit'] ) || ! is_numeric( $data['total'] ) || ! is_bool( $data['truncated'] ) ) {
				return new WP_Error(
					'invalid_cluster_list_envelope',
					'Cluster list response must include limit, total, and truncated when clusters is present.',
					array( 'status' => 502 )
				);
			}

			$clusters = $data['clusters'];
			$total = max( 0, (int) $data['total'] );
			$limit = max( 1, (int) $data['limit'] );
			$truncated = $data['truncated'];

			return new WP_REST_Response(
				array(
					'clusters' => $clusters,
					'limit' => $limit,
					'total' => $total,
					'truncated' => $truncated,
				),
				$response->get_status()
			);
		}

		// Legacy bare-array list payloads carry no total/limit metadata; the
		// recognition service always emits the canonical envelope, so fabricating
		// one here would invent contract metadata [rg-015]. Fail loudly instead.
		return new WP_Error(
			'invalid_cluster_list_envelope',
			'Cluster list response must be a canonical envelope with clusters, limit, total, and truncated.',
			array( 'status' => 502 )
		);
	}

	/**
	 * Normalize top-unlabeled proxy payloads with the same fail-loud contract
	 * as members/list (no fabricated total/truncated from bare arrays) [rg-015].
	 */
	public function normalize_top_unlabeled_response( WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		if ( isset( $data['clusters'] ) && is_array( $data['clusters'] ) ) {
			if ( ! isset( $data['limit'], $data['total'], $data['truncated'] ) || ! is_numeric( $data['limit'] ) || ! is_numeric( $data['total'] ) || ! is_bool( $data['truncated'] ) ) {
				return new WP_Error(
					'invalid_top_unlabeled_envelope',
					'Top-unlabeled clusters response must include limit, total, and truncated when clusters is present.',
					array( 'status' => 502 )
				);
			}

			$kept    = array();
			$dropped = 0;
			foreach ( $data['clusters'] as $cluster ) {
				if ( ! is_array( $cluster ) ) {
					continue;
				}
				$representatives = $cluster['representatives'] ?? null;
				if ( ! is_array( $representatives ) || array() === $representatives ) {
					++$dropped;
					continue;
				}
				$kept[] = $cluster;
			}

			$total = max( 0, (int) $data['total'] );

			return new WP_REST_Response(
				array(
					'clusters' => $kept,
					'limit' => max( 1, (int) $data['limit'] ),
					'total' => $total,
					'truncated' => $data['truncated'],
					'repair_pending' => $dropped > 0,
				),
				$response->get_status()
			);
		}

		// Legacy bare-array top-unlabeled payloads carry no total/limit metadata;
		// fabricating one here would invent contract metadata [rg-015].
		return new WP_Error(
			'invalid_top_unlabeled_envelope',
			'Top-unlabeled clusters response must be a canonical envelope with clusters, limit, total, and truncated.',
			array( 'status' => 502 )
		);
	}

	public function normalize_cluster_members_response( WP_REST_Response|WP_Error $response ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		if ( isset( $data['members'] ) && is_array( $data['members'] ) ) {
			if ( ! isset( $data['limit'], $data['total'], $data['truncated'] ) || ! is_numeric( $data['limit'] ) || ! is_numeric( $data['total'] ) || ! is_bool( $data['truncated'] ) ) {
				return new WP_Error(
					'invalid_cluster_members_envelope',
					'Cluster members response must include limit, total, and truncated when members is present.',
					array( 'status' => 502 )
				);
			}

			$members = $data['members'];
			$total = max( 0, (int) $data['total'] );
			$limit = max( 1, (int) $data['limit'] );
			$truncated = $data['truncated'];

			return new WP_REST_Response(
				array(
					'members' => $members,
					'limit' => $limit,
					'total' => $total,
					'truncated' => $truncated,
				),
				$response->get_status()
			);
		}

		// Legacy bare-array member payloads carry no total/limit metadata; the
		// recognition service always emits the canonical envelope, so fabricating
		// one here would invent contract metadata [rg-015]. Fail loudly instead.
		return new WP_Error(
			'invalid_cluster_members_envelope',
			'Cluster members response must be a canonical envelope with members, limit, total, and truncated.',
			array( 'status' => 502 )
		);
	}

	public function normalize_cluster_labels_response( WP_REST_Response|WP_Error $response, int $requested_limit ): WP_REST_Response|WP_Error {
		if ( ! ( $response instanceof WP_REST_Response ) ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		if ( isset( $data['labels'] ) && is_array( $data['labels'] ) ) {
			if ( ! isset( $data['limit'], $data['total'], $data['truncated'] ) || ! is_numeric( $data['limit'] ) || ! is_numeric( $data['total'] ) || ! is_bool( $data['truncated'] ) ) {
				return new WP_Error(
					'invalid_cluster_labels_envelope',
					'Cluster labels response must include limit, total, and truncated when labels is present.',
					array( 'status' => 502 )
				);
			}

			$labels = $this->cluster_mapper->map_labels_list( $data['labels'] );
			$total = max( 0, (int) $data['total'] );
			$limit = max( 1, (int) $data['limit'] );
			$truncated = $data['truncated'];

			return new WP_REST_Response(
				array(
					'labels' => $labels,
					'limit' => $limit,
					'total' => $total,
					'truncated' => $truncated,
				),
				$response->get_status()
			);
		}

		$labels = $this->cluster_mapper->map_labels_list( $data );
		return new WP_REST_Response(
			$this->build_cluster_labels_envelope( $labels, $requested_limit, count( $labels ) ),
			$response->get_status()
		);
	}
}
