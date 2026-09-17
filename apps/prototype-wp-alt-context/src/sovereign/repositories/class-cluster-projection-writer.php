<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

require_once __DIR__ . '/interface-clusters-repository.php';
require_once __DIR__ . '/trait-prepares-sql-queries.php';
require_once __DIR__ . '/class-cluster-curation-writer.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';
require_once dirname( __DIR__, 2 ) . '/api/services/class-person-resolution-service.php';
require_once dirname( __DIR__ ) . '/sync/class-outbox-writer.php';

use AltContext\Api\Services\PersonResolutionService;
use AltContext\Sovereign\Sync\OutboxWriter;
use AltContext\Support\DetectsSystemDefinedLabels;

use function array_key_exists;
use function count;
use function function_exists;
use function gmdate;
use function is_array;
use function is_float;
use function is_int;
use function is_object;
use function is_string;
use function is_wp_error;
use function json_encode;
use function max;
use function method_exists;
use function trim;
use function wp_is_uuid;
use function wp_json_encode;

class ClusterProjectionWriter {
	use DetectsSystemDefinedLabels;
	use PreparesSqlQueries;

	private string $table_name;

	public function __construct( string $table_name ) {
		$this->table_name = $table_name;
	}

	public function create_local_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count = 1 ): int|\WP_Error {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_cluster_uuid = trim( $cluster_uuid );
		$normalized_label = trim( $label );
		if ( '' === $normalized_tenant_id || '' === $normalized_cluster_uuid || '' === $normalized_label ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'insert' ) ) {
			return 0;
		}

		$resolved = null;
		if ( ! $this->is_reserved_label_shape( $normalized_label ) ) {
			$resolver = new PersonResolutionService();
			$resolved = $resolver->resolve_for_automatic_bind(
				$normalized_label,
				$normalized_tenant_id,
				$normalized_cluster_uuid,
				function ( string $person_uuid, string $name, array $tags ) use ( $normalized_tenant_id ): bool {
					$queued = ( new OutboxWriter() )->enqueue(
						$normalized_tenant_id,
						'person_created',
						'person',
						$person_uuid,
						0,
						1,
						array(
							'person_uuid' => $person_uuid,
							'name'        => $name,
							'tags'        => $tags,
						)
					);
					return false !== $queued;
				}
			);
			if ( is_wp_error( $resolved ) ) {
				return $resolved;
			}
			$normalized_label = trim( (string) $resolved['name'] );
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$inserted = $wpdb->insert(
			$this->table_name,
			array(
				'cluster_uuid' => $normalized_cluster_uuid,
				'tenant_id' => $normalized_tenant_id,
				'label' => $normalized_label,
				'curation_state' => 'uncurated',
				'identity_count' => max( 0, $identity_count ),
				'snapshot_version' => 0,
				'is_user_confirmed' => 1,
				'local_revision' => 1,
				'created_at' => $now_utc,
				'updated_at' => $now_utc,
				'last_synced_at' => $now_utc,
			),
			array( '%s', '%s', '%s', '%s', '%d', '%d', '%d', '%d', '%s', '%s', '%s' )
		);

		if ( ! is_int( $inserted ) || $inserted <= 0 ) {
			return is_int( $inserted ) ? $inserted : 0;
		}

		if ( is_array( $resolved ) ) {
			$bound = ( new ClusterCurationWriter( $this->table_name ) )->bind_person_to_cluster(
				$normalized_cluster_uuid,
				(int) $resolved['person_id'],
				$normalized_tenant_id,
				false
			);
			if ( false === $bound ) {
				return 0;
			}
		}

		return $inserted;
	}

	/**
	 * @param array<string,mixed> $snapshot_export Snapshot keys from recognition-cluster-snapshot.schema.json.
	 */
	public function upsert_projection_cluster( string $tenant_id, string $cluster_uuid, string $label, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false, array $snapshot_export = array() ): int {
		global $wpdb;

		$normalized_tenant_id = trim( $tenant_id );
		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_tenant_id || '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		$export = $this->normalize_snapshot_export( $snapshot_export );
		$sql = $this->prepare_query(
			'INSERT INTO %i
				(cluster_uuid, tenant_id, label, curation_state, representative_thumb_path, representative_id, is_pinned, identity_count, snapshot_version, is_user_confirmed, local_revision, created_at, updated_at, last_synced_at, representative_quality, quality_components, representative_media_id, undoable_merge_receipt_id)
			VALUES (%s, %s, %s, %s, %s, %s, %d, %d, %d, %d, %d, %s, %s, %s, NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'), NULLIF(%s, \'\'))
			ON DUPLICATE KEY UPDATE
				label = VALUES(label),
				curation_state = VALUES(curation_state),
				representative_thumb_path = VALUES(representative_thumb_path),
				representative_id = VALUES(representative_id),
				is_pinned = VALUES(is_pinned),
				identity_count = VALUES(identity_count),
				snapshot_version = GREATEST(snapshot_version, VALUES(snapshot_version)),
				is_user_confirmed = VALUES(is_user_confirmed),
				updated_at = VALUES(updated_at),
				last_synced_at = VALUES(last_synced_at),
				representative_quality = IF(%d, VALUES(representative_quality), representative_quality),
				quality_components = IF(%d, VALUES(quality_components), quality_components),
				representative_media_id = IF(%d, VALUES(representative_media_id), representative_media_id),
				undoable_merge_receipt_id = IF(%d, VALUES(undoable_merge_receipt_id), undoable_merge_receipt_id)',
			array(
				$this->table_name,
				$normalized_cluster_uuid,
				$normalized_tenant_id,
				trim( $label ),
				'uncurated',
				null === $representative_thumb_path ? null : trim( $representative_thumb_path ),
				$this->normalize_optional_text( $representative_id ),
				$is_pinned ? 1 : 0,
				max( 0, $identity_count ),
				max( 0, $snapshot_version ),
				0,
				0,
				$now_utc,
				$now_utc,
				$now_utc,
				$export['representative_quality'],
				$export['quality_components'],
				$export['representative_media_id'],
				$export['undoable_merge_receipt_id'],
				$export['apply'],
				$export['apply'],
				$export['apply'],
				$export['apply'],
			)
		);

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	public function update_projection_cluster( string $cluster_uuid, int $identity_count, int $snapshot_version, ?string $representative_thumb_path = null, ?string $representative_id = null, bool $is_pinned = false ): int {
		global $wpdb;

		$normalized_cluster_uuid = trim( $cluster_uuid );
		if ( '' === $normalized_cluster_uuid ) {
			return 0;
		}

		if ( ! isset( $wpdb ) || ! is_object( $wpdb ) || ! method_exists( $wpdb, 'query' ) ) {
			return 0;
		}

		$now_utc = gmdate( 'Y-m-d H:i:s' );
		if ( null === $representative_thumb_path ) {
			$sql = $this->prepare_query(
				'UPDATE %i
				SET identity_count = %d,
					snapshot_version = GREATEST(snapshot_version, %d),
					representative_id = %s,
					is_pinned = %d,
					updated_at = %s,
					last_synced_at = %s
				WHERE cluster_uuid = %s',
				array(
					$this->table_name,
					max( 0, $identity_count ),
					max( 0, $snapshot_version ),
					$this->normalize_optional_text( $representative_id ),
					$is_pinned ? 1 : 0,
					$now_utc,
					$now_utc,
					$normalized_cluster_uuid,
				)
			);
		} else {
			$sql = $this->prepare_query(
				'UPDATE %i
				SET identity_count = %d,
					snapshot_version = GREATEST(snapshot_version, %d),
					representative_thumb_path = %s,
					representative_id = %s,
					is_pinned = %d,
					updated_at = %s,
					last_synced_at = %s
				WHERE cluster_uuid = %s',
				array(
					$this->table_name,
					max( 0, $identity_count ),
					max( 0, $snapshot_version ),
					trim( $representative_thumb_path ),
					$this->normalize_optional_text( $representative_id ),
					$is_pinned ? 1 : 0,
					$now_utc,
					$now_utc,
					$normalized_cluster_uuid,
				)
			);
		}

		if ( ! is_string( $sql ) || '' === $sql ) {
			return 0;
		}

		// phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared -- Query is prepared above and executed as-is.
		$query_result = $wpdb->query( $sql );
		return is_int( $query_result ) ? $query_result : 0;
	}

	private function normalize_optional_text( ?string $value ): ?string {
		if ( ! is_string( $value ) ) {
			return null;
		}

		$normalized = trim( $value );
		return '' !== $normalized ? $normalized : null;
	}

	/**
	 * @param array<string,mixed> $snapshot_export
	 * @return array{representative_quality: string, quality_components: string, representative_media_id: string, undoable_merge_receipt_id: string, apply: int}
	 */
	private function normalize_snapshot_export( array $snapshot_export ): array {
		$apply = $this->snapshot_export_is_present( $snapshot_export ) ? 1 : 0;
		if ( 0 === $apply ) {
			return array(
				'representative_quality' => '',
				'quality_components' => '',
				'representative_media_id' => '',
				'undoable_merge_receipt_id' => '',
				'apply' => 0,
			);
		}

		return array(
			'representative_quality' => $this->normalize_representative_quality(
				$snapshot_export[ ClustersRepositoryInterface::SNAPSHOT_EXPORT_REPRESENTATIVE_QUALITY ] ?? null
			),
			'quality_components' => $this->normalize_quality_components(
				$snapshot_export[ ClustersRepositoryInterface::SNAPSHOT_EXPORT_QUALITY_COMPONENTS ] ?? null
			),
			'representative_media_id' => $this->normalize_representative_media_id(
				$snapshot_export[ ClustersRepositoryInterface::SNAPSHOT_EXPORT_REPRESENTATIVE_MEDIA_ID ] ?? null
			),
			'undoable_merge_receipt_id' => $this->normalize_undoable_merge_receipt_id(
				$snapshot_export[ ClustersRepositoryInterface::SNAPSHOT_EXPORT_UNDOABLE_MERGE_RECEIPT_ID ] ?? null
			),
			'apply' => 1,
		);
	}

	/**
	 * @param array<string,mixed> $snapshot_export
	 */
	private function snapshot_export_is_present( array $snapshot_export ): bool {
		foreach ( array(
			ClustersRepositoryInterface::SNAPSHOT_EXPORT_REPRESENTATIVE_QUALITY,
			ClustersRepositoryInterface::SNAPSHOT_EXPORT_QUALITY_COMPONENTS,
			ClustersRepositoryInterface::SNAPSHOT_EXPORT_REPRESENTATIVE_MEDIA_ID,
			ClustersRepositoryInterface::SNAPSHOT_EXPORT_UNDOABLE_MERGE_RECEIPT_ID,
		) as $key ) {
			if ( array_key_exists( $key, $snapshot_export ) ) {
				return true;
			}
		}

		return false;
	}

	private function normalize_representative_quality( mixed $value ): string {
		if ( ! is_int( $value ) && ! is_float( $value ) ) {
			return '';
		}

		$quality = (float) $value;
		if ( $quality < 0.0 || $quality > 1.0 ) {
			return '';
		}

		return (string) $quality;
	}

	private function normalize_quality_components( mixed $value ): string {
		if ( ! is_array( $value ) ) {
			return '';
		}

		$required = array( 'confidence', 'bbox_area', 'sharpness', 'occlusion_severity' );
		foreach ( $required as $key ) {
			if ( ! array_key_exists( $key, $value ) ) {
				return '';
			}
		}
		if ( count( $value ) !== 4 ) {
			return '';
		}

		$normalized = array();
		foreach ( $required as $key ) {
			$component = $value[ $key ];
			if ( null === $component ) {
				$normalized[ $key ] = null;
				continue;
			}
			if ( ! is_int( $component ) && ! is_float( $component ) ) {
				return '';
			}
			$number = (float) $component;
			if ( 'bbox_area' === $key ) {
				if ( $number < 0.0 ) {
					return '';
				}
			} elseif ( $number < 0.0 || $number > 1.0 ) {
				return '';
			}
			$normalized[ $key ] = is_int( $component ) ? $component : $number;
		}

		$encoded = function_exists( 'wp_json_encode' ) ? wp_json_encode( $normalized ) : json_encode( $normalized );
		return is_string( $encoded ) && '' !== $encoded ? $encoded : '';
	}

	private function normalize_representative_media_id( mixed $value ): string {
		if ( is_int( $value ) ) {
			return $value >= 1 ? (string) $value : '';
		}
		if ( is_float( $value ) && (float) (int) $value === $value && $value >= 1.0 ) {
			return (string) (int) $value;
		}

		return '';
	}

	private function normalize_undoable_merge_receipt_id( mixed $value ): string {
		if ( ! is_string( $value ) ) {
			return '';
		}

		$normalized = trim( $value );
		if ( '' === $normalized || ! wp_is_uuid( $normalized ) ) {
			return '';
		}

		return $normalized;
	}
}
