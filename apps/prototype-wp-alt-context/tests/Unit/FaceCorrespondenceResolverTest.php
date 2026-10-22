<?php

declare(strict_types=1);

namespace AltContext\Tests\Unit;

use AltContext\Sovereign\Curation\FaceCorrespondenceResolver;
use PHPUnit\Framework\TestCase;

final class FaceCorrespondenceResolverTest extends TestCase {
	public static function face( string $id = 'face-1', string $observation = 'obs-1' ): array {
		return array(
			'identity_uuid' => $id, 'tenant_id' => 'tenant', 'attachment_id' => 42,
			'lifecycle_eligible' => true,
			'face_evidence_v1' => array(
				'identity_namespace_id' => 'namespace', 'observation_id' => $observation,
				'source_sha256' => str_repeat( 'a', 64 ), 'raster_sha256' => str_repeat( 'b', 64 ),
				'decode_recipe_id' => 'rgb-u8-v1', 'raster_width' => 100, 'raster_height' => 80,
				'region' => array( 'x' => 1, 'y' => 2, 'width' => 20, 'height' => 30 ),
			),
		);
	}
	private function resolve( array $faces, ?array $anchors = null, array $overrides = array(), array $intent = array() ): array {
		$anchor = self::face();
		$anchor['person_uuid'] = 'person';
		$anchor['authority_state'] = 'active';
		$anchor['binding_intent_id'] = 'intent';
		return ( new FaceCorrespondenceResolver() )->resolve(
			array_replace( array( 'tenant_id' => 'tenant', 'identity_namespace_id' => 'namespace', 'snapshot_version' => 7, 'complete' => true, 'claims_complete' => true, 'available' => true, 'lifecycle_attested' => true, 'faces' => $faces ), $overrides ),
			$anchors ?? array( 'anchor-1' => $anchor ),
			array_replace( array( 'person_uuid' => 'person', 'binding_intent_revision' => 1, 'binding_intent_id' => 'intent', 'auto_rebind_suppressed' => false, 'ancestry_attested' => true ), $intent )
		);
	}
	public function test_same_uuid_changed_bytes_abstains_but_unchanged_control_is_exact(): void {
		$face = self::face();
		self::assertSame( 'exact', $this->resolve( array( $face ) )['correspondence_status'] );
		$face['face_evidence_v1']['source_sha256'] = str_repeat( 'c', 64 );
		self::assertSame( 'changed_source', $this->resolve( array( $face ) )['correspondence_status'] );
	}
	public function test_complete_empty_is_not_partial_or_failed_empty(): void {
		self::assertSame( 'no_match', $this->resolve( array() )['correspondence_status'] );
		self::assertSame( 'insufficient_evidence', $this->resolve( array(), null, array( 'complete' => false ) )['correspondence_status'] );
		self::assertSame( 'unavailable', $this->resolve( array(), null, array( 'available' => false ) )['correspondence_status'] );
	}
	public function test_duplicate_observations_and_competing_claims_abstain(): void {
		self::assertSame( 'ambiguous', $this->resolve( array( self::face(), self::face( 'face-2' ) ) )['correspondence_status'] );
		$a = self::face() + array( 'person_uuid' => 'person', 'authority_state' => 'active', 'binding_intent_id' => 'intent' );
		$b = array_replace( $a, array( 'person_uuid' => 'other' ) );
		self::assertSame( 'ambiguous', $this->resolve( array( self::face() ), array( 'a' => $a, 'b' => $b ) )['correspondence_status'] );
	}
	public function test_suppression_legacy_lifecycle_and_namespace_fail_closed(): void {
		self::assertSame( 'unavailable', $this->resolve( array( self::face() ), null, array(), array( 'auto_rebind_suppressed' => true ) )['correspondence_status'] );
		$a = self::face() + array( 'person_uuid' => 'person', 'authority_state' => 'historical' );
		unset( $a['face_evidence_v1'] );
		self::assertSame( 'insufficient_evidence', $this->resolve( array( self::face() ), array( 'legacy' => $a ) )['correspondence_status'] );
		self::assertSame( 'unavailable', $this->resolve( array( self::face() ), null, array( 'lifecycle_attested' => false ) )['correspondence_status'] );
		self::assertSame( 'namespace_mismatch', $this->resolve( array( self::face() ), null, array( 'identity_namespace_id' => 'reset' ) )['correspondence_status'] );
	}
	public function test_exact_result_covers_full_set_and_snapshot_and_ignores_presentation_urls(): void {
		$face = self::face();
		$face['thumb_url'] = 'https://presentation.invalid/new';
		$result = $this->resolve( array( $face ) );
		self::assertSame( 'exact', $result['correspondence_status'] );
		self::assertSame( 7, $result['snapshot_version'] );
		self::assertSame( 'namespace', $result['identity_namespace_id'] );
		self::assertSame( 'anchor-1', $result['matched_faces'][0]['anchor_ref'] );
		self::assertSame( 'face-1', $result['matched_faces'][0]['identity_uuid'] );
		self::assertNotSame( $result['input_digest'], $this->resolve( array( $face ), null, array( 'snapshot_version' => 8 ) )['input_digest'] );
		$extra = self::face( 'extra', 'obs-extra' );
		$extra['face_evidence_v1']['region']['x'] = 40;
		self::assertSame( 'insufficient_evidence', $this->resolve( array( $face, $extra ) )['correspondence_status'] );
	}
	public function test_each_evidence_component_and_lifecycle_is_required(): void {
		foreach ( array( 'observation_id', 'source_sha256', 'raster_sha256', 'decode_recipe_id', 'raster_width', 'raster_height', 'region' ) as $field ) {
			$face = self::face();
			$value = $face['face_evidence_v1'][ $field ];
			$face['face_evidence_v1'][ $field ] = is_int( $value ) ? $value + 1 : ( is_array( $value ) ? array_replace( $value, array( 'x' => 2 ) ) : ( str_ends_with( $field, 'sha256' ) ? str_repeat( 'c', 64 ) : 'changed' ) );
			self::assertSame( 'changed_source', $this->resolve( array( $face ) )['correspondence_status'], $field );
			unset( $face['face_evidence_v1'][ $field ] );
			self::assertSame( 'insufficient_evidence', $this->resolve( array( $face ) )['correspondence_status'], $field );
		}
		$face = self::face();
		$face['lifecycle_eligible'] = false;
		self::assertSame( 'insufficient_evidence', $this->resolve( array( $face ) )['correspondence_status'] );
		self::assertSame( 'insufficient_evidence', $this->resolve( array(), null, array( 'claims_complete' => false ) )['correspondence_status'] );
	}
	public function test_distinct_faces_need_distinct_regions_and_observations(): void {
		$one = self::face();
		$two = self::face( 'face-2', 'obs-2' );
		self::assertSame( 'ambiguous', $this->resolve( array( $one, $two ) )['correspondence_status'] );
		$two['face_evidence_v1']['region']['x'] = 40;
		$anchors = array();
		foreach ( array( $one, $two ) as $i => $face ) {
			$anchors[ 'anchor-' . $i ] = $face + array( 'person_uuid' => 'person', 'authority_state' => 'active', 'binding_intent_id' => 'intent' );
		}
		$result = $this->resolve( array( $one, $two ), $anchors );
		self::assertSame( 'exact', $result['correspondence_status'] );
		self::assertCount( 2, $result['matched_faces'] );
		$anchors['anchor-1']['face_evidence_v1']['region']['x'] = 1;
		self::assertSame( 'ambiguous', $this->resolve( array( $one, $two ), $anchors )['correspondence_status'] );
	}
}
