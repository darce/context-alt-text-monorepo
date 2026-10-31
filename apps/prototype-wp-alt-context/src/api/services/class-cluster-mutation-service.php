<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../Sovereign/Curation/WpBindingIntentParticipant.php';
require_once __DIR__ . '/../../support/trait-detects-system-defined-labels.php';

use AltContext\Sovereign\Curation\WpBindingIntentParticipant;
use AltContext\Support\DetectsSystemDefinedLabels;
use WP_Error;
use WP_REST_Response;

/** Explicit intent branch of the existing authenticated cluster PATCH route. */
final class ClusterMutationService {
	use DetectsSystemDefinedLabels;

	public function apply_binding_intent( string $tenant, string $cluster, $input ): WP_REST_Response|WP_Error {
		global $wpdb;
		if ( ! is_array( $input ) || ! is_string( $input['kind'] ?? null ) ) {
			return new WP_Error( 'invalid_binding_intent', 'A typed binding intent is required.', array( 'status' => 400 ) );
		}
		if ( in_array( $input['kind'], array( 'positive', 'bind', 'reapply', 'undo' ), true ) ) {
			return new WP_Error( 'binding_review_unavailable', 'Reviewed source and ordered recovery are not available. The name remains saved.', array( 'status' => 409 ) );
		}
		$allowed = array( 'kind', 'person_uuid' );
		if ( 'inspect' !== $input['kind'] ) {
			$allowed = array_merge( $allowed, array( 'request_id', 'expected_revision', 'guards' ) );
			if ( 'rename' === $input['kind'] ) {
				$allowed[] = 'name';
			}
		}
		if ( array_diff( array_keys( $input ), $allowed ) || ! in_array( $input['kind'], array( 'inspect', 'unlink', 'rename' ), true ) || ! is_string( $input['person_uuid'] ?? null ) || '' === trim( $input['person_uuid'] ) || '' === trim( $tenant ) || '' === trim( $cluster ) ) {
			return new WP_Error( 'invalid_binding_intent', 'Invalid local intent fields.', array( 'status' => 400 ) );
		}
		if ( 'inspect' !== $input['kind'] && ( ! is_string( $input['request_id'] ?? null ) || '' === trim( $input['request_id'] ) || ! is_int( $input['expected_revision'] ?? null ) || $input['expected_revision'] < 0 || ! is_array( $input['guards'] ?? null ) ) ) {
			return new WP_Error( 'invalid_binding_intent', 'Request identity, revision and local guards are required.', array( 'status' => 400 ) );
		}
		if ( 'rename' === $input['kind'] ) {
			$name = $input['name'] ?? null;
			if ( ! is_string( $name ) || '' === trim( $name ) || $name !== sanitize_text_field( $name ) || mb_strlen( $name ) > 255 || $this->is_reserved_label_shape( $name ) ) {
				return new WP_Error( 'invalid_binding_intent', 'A valid person name is required.', array( 'status' => 400 ) );
			}
		}
		if ( ! is_object( $wpdb ) ) {
			return new WP_Error( 'acx_db_error', 'Database access is unavailable.', array( 'status' => 500 ) );
		}
		try {
			$participant = new WpBindingIntentParticipant( $wpdb );
			$data = 'inspect' === $input['kind']
				? $participant->inspect( $tenant, $input['person_uuid'], $cluster )
				: $participant->apply( $tenant, $cluster, $input );
			return new WP_REST_Response( array( 'binding_intent' => $data, 'synced' => false ), 200 );
		} catch ( \InvalidArgumentException $error ) {
			return new WP_Error( 'invalid_binding_intent', 'The binding intent is incomplete.', array( 'status' => 400 ) );
		} catch ( \DomainException $error ) {
			return new WP_Error( 'binding_intent_changed', 'Local inputs changed or earlier delivery needs review. Reload and retry.', array( 'status' => 409 ) );
		} catch ( \Throwable $error ) {
			return new WP_Error( 'acx_db_error', 'The local intent could not be saved. Retry.', array( 'status' => 500 ) );
		}
	}
}
