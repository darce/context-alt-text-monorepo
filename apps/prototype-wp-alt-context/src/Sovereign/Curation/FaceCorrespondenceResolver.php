<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Curation;

/** Pure static source correspondence, never live URL validation or person inference. */
final class FaceCorrespondenceResolver {
	public const EXACT = 'exact';
	public const NO_MATCH = 'no_match';
	public const CHANGED_SOURCE = 'changed_source';
	public const NAMESPACE_MISMATCH = 'namespace_mismatch';
	public const AMBIGUOUS = 'ambiguous';
	public const INSUFFICIENT_EVIDENCE = 'insufficient_evidence';
	public const UNAVAILABLE = 'unavailable';

	/**
	 * Incoming is the COMPLETE frozen service view, never the protected overlay.
	 * anchors includes ALL active competing person claims in that tenant/scope.
	 * The caller must attest completeness of that claim read as well as ancestry.
	 * Fresh review is deliberately not an input that can make this result exact.
	 */
	public function resolve( array $incoming, array $anchors, array $intent ): array {
		$result = array(
			'correspondence_status' => self::INSUFFICIENT_EVIDENCE,
			'matched_faces' => array(),
			'snapshot_version' => $incoming['snapshot_version'] ?? null,
			'identity_namespace_id' => $incoming['identity_namespace_id'] ?? null,
			'input_digest' => BindingIntentJournal::fingerprint( array( $incoming, $anchors, $intent ) ),
		);
		if ( true !== ( $incoming['available'] ?? false ) || true !== ( $incoming['lifecycle_attested'] ?? false ) || true !== ( $intent['ancestry_attested'] ?? false ) || false !== ( $intent['auto_rebind_suppressed'] ?? null ) ) {
			$result['correspondence_status'] = self::UNAVAILABLE;
			return $result;
		}
		if ( true !== ( $incoming['complete'] ?? false ) || true !== ( $incoming['claims_complete'] ?? false ) || ! is_int( $incoming['snapshot_version'] ?? null ) || $incoming['snapshot_version'] < 0 || ! is_array( $incoming['faces'] ?? null ) || ! self::nonempty( $incoming['tenant_id'] ?? null ) || ! self::nonempty( $incoming['identity_namespace_id'] ?? null ) || ! self::nonempty( $intent['person_uuid'] ?? null ) || ! self::nonempty( $intent['binding_intent_id'] ?? null ) || ! is_int( $intent['binding_intent_revision'] ?? null ) ) {
			return $result;
		}
		$tenant = $incoming['tenant_id'];
		$namespace = $incoming['identity_namespace_id'];
		$eligible = array();
		$own = array();
		$anchor_sources = array();
		foreach ( $anchors as $reference => $anchor ) {
			if ( ! is_array( $anchor ) ) {
				return $result;
			}
			if ( 'active' !== ( $anchor['authority_state'] ?? null ) ) {
				continue;
			}
			if ( ! self::valid_face( $anchor ) || $tenant !== $anchor['tenant_id'] || ! self::nonempty( $anchor['binding_intent_id'] ?? null ) || ! self::nonempty( $anchor['person_uuid'] ?? null ) ) {
				return $result;
			}
			if ( $namespace !== $anchor['face_evidence_v1']['identity_namespace_id'] ) {
				$result['correspondence_status'] = self::NAMESPACE_MISMATCH;
				return $result;
			}
			$source_key = self::source_key( $anchor );
			if ( isset( $anchor_sources[ $source_key ] ) ) {
				$result['correspondence_status'] = self::AMBIGUOUS;
				return $result;
			}
			$anchor_sources[ $source_key ] = true;
			$observation = $anchor['face_evidence_v1']['observation_id'];
			$eligible[ $observation ][ $reference ] = $anchor;
			if ( $anchor['person_uuid'] === $intent['person_uuid'] ) {
				$own[ $reference ] = $anchor;
			}
		}
		// Absent historical proof never becomes a verified empty match.
		if ( array() === $own ) {
			return $result;
		}
		$seen_sources = array();
		$seen_ids = array();
		$seen_observations = array();
		$matched = array();
		$unmatched = false;
		foreach ( $incoming['faces'] as $face ) {
			if ( ! is_array( $face ) || ! self::valid_face( $face ) || $tenant !== $face['tenant_id'] ) {
				return $result;
			}
			$proof = $face['face_evidence_v1'];
			if ( $namespace !== $proof['identity_namespace_id'] ) {
				$result['correspondence_status'] = self::NAMESPACE_MISMATCH;
				return $result;
			}
			$observation = $proof['observation_id'];
			$id = $face['identity_uuid'];
			$source_key = self::source_key( $face );
			if ( isset( $seen_sources[ $source_key ] ) || isset( $seen_ids[ $id ] ) || isset( $seen_observations[ $observation ] ) ) {
				$result['correspondence_status'] = self::AMBIGUOUS;
				return $result;
			}
			$seen_sources[ $source_key ] = true;
			$seen_ids[ $id ] = true;
			$seen_observations[ $observation ] = true;
			$candidates = $eligible[ $observation ] ?? array();
			// A retained row UUID with a different observation is changed, not proof.
			foreach ( $own as $anchor ) {
				if ( $anchor['identity_uuid'] === $id && $anchor['face_evidence_v1']['observation_id'] !== $observation ) {
					$result['correspondence_status'] = self::CHANGED_SOURCE;
					return $result;
				}
			}
			if ( count( $candidates ) > 1 ) {
				$result['correspondence_status'] = self::AMBIGUOUS;
				return $result;
			}
			if ( array() === $candidates ) {
				$unmatched = true;
				continue;
			}
			$reference = array_key_first( $candidates );
			$anchor = $candidates[ $reference ];
			if ( $face['attachment_id'] !== $anchor['attachment_id'] || BindingIntentJournal::fingerprint( $proof ) !== BindingIntentJournal::fingerprint( $anchor['face_evidence_v1'] ) ) {
				$result['correspondence_status'] = self::CHANGED_SOURCE;
				return $result;
			}
			if ( $anchor['person_uuid'] !== $intent['person_uuid'] ) {
				$result['correspondence_status'] = self::AMBIGUOUS;
				return $result;
			}
			$matched[] = array(
				'identity_uuid' => $id,
				'anchor_ref' => $reference,
				'proof_ref' => array( 'tenant_id' => $tenant, 'identity_namespace_id' => $namespace, 'observation_id' => $observation ),
			);
		}
		if ( $unmatched ) {
			$result['correspondence_status'] = array() === $matched ? self::NO_MATCH : self::INSUFFICIENT_EVIDENCE;
			return $result;
		}
		$result['correspondence_status'] = array() === $matched ? self::NO_MATCH : self::EXACT;
		$result['matched_faces'] = $matched;
		return $result;
	}

	/** Validity is explicit producer input, not inferred from UUIDs or pixels. */
	public static function valid_face( array $face ): bool {
		if ( true !== ( $face['lifecycle_eligible'] ?? false ) || ! self::nonempty( $face['tenant_id'] ?? null ) || ! self::nonempty( $face['identity_uuid'] ?? null ) || ! is_int( $face['attachment_id'] ?? null ) || $face['attachment_id'] <= 0 || ! is_array( $face['face_evidence_v1'] ?? null ) ) {
			return false;
		}
		$proof = $face['face_evidence_v1'];
		foreach ( array( 'identity_namespace_id', 'observation_id', 'decode_recipe_id' ) as $field ) {
			if ( ! self::nonempty( $proof[ $field ] ?? null ) ) {
				return false;
			}
		}
		foreach ( array( 'source_sha256', 'raster_sha256' ) as $field ) {
			if ( ! is_string( $proof[ $field ] ?? null ) || 1 !== preg_match( '/^[a-f0-9]{64}$/D', $proof[ $field ] ) ) {
				return false;
			}
		}
		foreach ( array( 'raster_width', 'raster_height' ) as $field ) {
			if ( ! is_int( $proof[ $field ] ?? null ) || $proof[ $field ] <= 0 ) {
				return false;
			}
		}
		$region = $proof['region'] ?? null;
		if ( ! is_array( $region ) ) {
			return false;
		}
		foreach ( array( 'x', 'y', 'width', 'height' ) as $field ) {
			if ( ! is_int( $region[ $field ] ?? null ) ) {
				return false;
			}
		}
		return $region['x'] >= 0 && $region['y'] >= 0 && $region['width'] > 0 && $region['height'] > 0 && $region['x'] <= $proof['raster_width'] - $region['width'] && $region['y'] <= $proof['raster_height'] - $region['height'];
	}

	private static function source_key( array $face ): string {
		$proof = $face['face_evidence_v1'];
		unset( $proof['observation_id'] );
		return BindingIntentJournal::fingerprint( array( $face['tenant_id'], $face['attachment_id'], $proof ) );
	}

	private static function nonempty( $value ): bool {
		return is_string( $value ) && '' !== trim( $value );
	}
}
