<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

require_once __DIR__ . '/../../support/class-telemetry.php';
require_once __DIR__ . '/../../sovereign/repositories/class-description-usage-repository.php';
require_once __DIR__ . '/class-description-budget-service.php';
require_once __DIR__ . '/../../sovereign/repositories/class-identity-members-repository.php';
require_once __DIR__ . '/../class-alt-style.php';

use AltContext\Api\AltStyle;
use AltContext\Api\DescribeHostInterface;
use AltContext\Sovereign\Repositories\IdentityMembersRepository;
use AltContext\Sovereign\Repositories\IdentityMembersRepositoryInterface;
use AltContext\Support\Telemetry;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function array_filter;
use function array_key_exists;
use function array_slice;
use function array_values;
use function basename;
use function get_attached_file;
use function get_option;
use function get_post_meta;
use function get_post;
use function get_site_url;
use function gmdate;
use function is_array;
use function is_numeric;
use function is_object;
use function is_readable;
use function is_string;
use function is_wp_error;
use function max;
use function microtime;
use function pathinfo;
use function preg_match;
use function round;
use function sprintf;
use function strlen;
use function strtolower;
use function trim;
use function update_post_meta;
use function wp_get_object_terms;
use function wp_json_encode;
use function wp_update_post;

use const PATHINFO_EXTENSION;

/**
 * E19-1 S6 / E20-10: resolve one WordPress attachment, read its bytes, attach a
 * bounded `context_pack` (attachment metadata + roster-bound identity context),
 * and dispatch a single-image multipart request to the backend
 * `/scene/describe/multipart` route. Identity guardrail (E20-10): only an
 * assigned, user-confirmed roster person is named; unconfirmed, ambiguous, or
 * machine-only faces are never named and surface `review_reasons` instead. The
 * backend `VisualFactsResponse` is passed through unchanged; a malformed upstream
 * envelope is rejected with an explicit `502 invalid_description_envelope`
 * (rg-015 — never fabricate `cached`/`data_source`/provenance fields, never add
 * list-pagination fields). The typed `context_pack` key is consumed by the
 * backend `DescribeImageEnvelope` from E20-9 (merge E20-9 before E20-10).
 */
class DescribeMediaService {
	private const MULTIPART_MAX_BYTES = 25 * 1024 * 1024;
	private const ALT_TEXT_META_KEY = '_wp_attachment_image_alt';
	private const PROVENANCE_META_KEY = '_acx_description_provenance';

	/**
	 * The 17 provenance-bearing fields the backend contract guarantees
	 * (packages/shared-contracts/schemas/image-description-response.schema.json).
	 * The proxy validates the upstream payload carries every one before
	 * passing it through — a missing field means the boundary contract was
	 * violated. Includes VLM-3 wire fields `tier` (compute tier:
	 * provisional_cpu|final_gpu) and `result_generation`. Do not confuse
	 * response `tier` with the plugin billing option `acx_tier`.
	 *
	 * @var string[]
	 */
	private const REQUIRED_RESPONSE_FIELDS = array(
		'tenant_id',
		'media_id',
		'image_hash',
		'context_hash',
		'adapter',
		'model_id',
		'model_version',
		'prompt_or_task_version',
		'visual_facts',
		'alt_text_draft',
		'context_used',
		'provider_disclosure',
		'cached',
		'duration_ms',
		'retention_class',
		'tier',
		'result_generation',
	);

	private DescribeHostInterface $host;
	private DescriptionBudgetService $budget_service;
	private IdentityMembersRepositoryInterface $identity_members_repository;

	public function __construct( DescribeHostInterface $host, ?DescriptionBudgetService $budget_service = null, ?IdentityMembersRepositoryInterface $identity_members_repository = null ) {
		$this->host                        = $host;
		$this->budget_service              = $budget_service ?? new DescriptionBudgetService();
		$this->identity_members_repository = $identity_members_repository ?? new IdentityMembersRepository();
	}

	public function describe_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$started_at = microtime( true );
		$media_id   = absint( $request->get_param( 'media_id' ) );
		if ( $media_id <= 0 ) {
			return new WP_Error(
				'describe_invalid_media_id',
				'A positive media_id is required.',
				array( 'status' => 400 )
			);
		}

		$budget_gate = $this->budget_service->check_budget();
		if ( false === ( $budget_gate['allowed'] ?? false ) ) {
			return new WP_Error(
				(string) ( $budget_gate['code'] ?? 'description_budget_denied' ),
				(string) ( $budget_gate['message'] ?? 'Description generation budget denied this request.' ),
				array(
					'status' => 429,
					'budget' => $budget_gate,
				)
			);
		}

		$path = get_attached_file( $media_id, true );
		if ( ! is_string( $path ) || '' === $path || ! is_readable( $path ) ) {
			return new WP_Error(
				'describe_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is missing or not readable.', $media_id ),
				array( 'status' => 404 )
			);
		}

		// Reject oversize on a cheap stat before loading the whole file into
		// memory; the post-read strlen check below still guards the exact size.
		$stat_size = @filesize( $path );
		if ( is_int( $stat_size ) && $stat_size > self::MULTIPART_MAX_BYTES ) {
			return $this->payload_too_large_error( $media_id, $stat_size );
		}

		$bytes = @file_get_contents( $path );
		if ( false === $bytes || '' === $bytes ) {
			return new WP_Error(
				'describe_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is empty or unreadable.', $media_id ),
				array( 'status' => 404 )
			);
		}

		if ( strlen( $bytes ) > self::MULTIPART_MAX_BYTES ) {
			return $this->payload_too_large_error( $media_id, strlen( $bytes ) );
		}

		$multipart_body = array(
			'request' => wp_json_encode(
				array(
					'tenant_id' => $this->host->get_tenant_id(),
					'media_id'  => $media_id,
					'context_pack' => $this->build_context_pack( $media_id, $path ),
				)
			),
			'image_' . $media_id => array(
				'filename'     => basename( $path ),
				'content'      => $bytes,
				'content_type' => $this->resolve_image_mime_type( $path, $media_id ),
			),
		);

		$response = $this->host->proxy_recognition_request(
			'POST',
			'/scene/describe/multipart',
			$multipart_body,
			array(),
			'description',
			'multipart',
			self::MULTIPART_MAX_BYTES
		);

		if ( is_wp_error( $response ) ) {
			$this->record_error_from_wp_error( $media_id, $response, 'backend', true );
			return $response;
		}

		$result = $this->validate_description_envelope( $response, $media_id );
		if ( is_wp_error( $result ) ) {
			$this->record_error_from_wp_error( $media_id, $result, 'validation', false );
			return $result;
		}

		if ( $result->get_status() >= 400 ) {
			$this->record_error_from_response( $media_id, $result );
			return $result;
		}

		$this->record_success_from_response( $media_id, $result, $started_at );

		if ( ! $this->should_write_alt_text( $request ) ) {
			return $result;
		}

		return $this->apply_alt_text_write_policy( $result, $media_id, $this->should_force_alt_text_write( $request ) );
	}

	/**
	 * rg-015: pass the backend payload through verbatim on success, but never
	 * fabricate a description envelope when the upstream shape is wrong. Upstream
	 * 4xx/5xx errors are forwarded unchanged; a 2xx body that omits any required
	 * provenance field is an explicit boundary violation (502).
	 *
	 * `alt_text_draft` must be present *and* a string. A non-string is a schema
	 * violation (502). An empty string is allowed through validation — the model
	 * may produce nothing useful — and write policy skips it instead of 502ing
	 * (see {@see apply_alt_text_write_policy()} / BR-104).
	 */
	private function validate_description_envelope( WP_REST_Response $response, int $media_id ): WP_REST_Response|WP_Error {
		if ( $response->get_status() >= 400 ) {
			return $response;
		}

		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $this->invalid_envelope_error( $media_id, 'response body was not a JSON object' );
		}

		foreach ( self::REQUIRED_RESPONSE_FIELDS as $field ) {
			if ( ! array_key_exists( $field, $data ) ) {
				return $this->invalid_envelope_error( $media_id, sprintf( "missing required field '%s'", $field ) );
			}
		}

		// BR-116: contract field is a string; refuse non-string at the boundary
		// rather than coerce (coercion made REST store '' while CLI stored '42').
		if ( ! is_string( $data['alt_text_draft'] ) ) {
			return $this->invalid_envelope_error( $media_id, "field 'alt_text_draft' must be a string" );
		}

		return $response;
	}

	/**
	 * Single normaliser for `alt_text_draft` across REST write policy and CLI
	 * generate-write (BR-116). Non-strings become `''` so write paths share one
	 * empty-draft skip; the real describe path rejects non-strings earlier with
	 * 502 in {@see validate_description_envelope()}.
	 *
	 * @param mixed $value Raw `alt_text_draft` from a describe envelope.
	 */
	public static function normalize_alt_text_draft( mixed $value ): string {
		if ( ! is_string( $value ) ) {
			return '';
		}

		return trim( $value );
	}

	private function should_write_alt_text( WP_REST_Request $request ): bool {
		return $this->truthy_request_param( $request->get_param( 'write_alt' ) );
	}

	private function should_force_alt_text_write( WP_REST_Request $request ): bool {
		return $this->truthy_request_param( $request->get_param( 'force' ) );
	}

	private function truthy_request_param( mixed $value ): bool {
		if ( is_bool( $value ) ) {
			return $value;
		}
		if ( is_string( $value ) ) {
			$normalized = strtolower( trim( $value ) );
			return '1' === $normalized || 'true' === $normalized || 'yes' === $normalized || 'on' === $normalized;
		}
		return 1 === $value || 1.0 === $value;
	}

	private function apply_alt_text_write_policy( WP_REST_Response $response, int $media_id, bool $force ): WP_REST_Response {
		$data = $response->get_data();
		if ( ! is_array( $data ) ) {
			return $response;
		}

		// Shared with CLI (BR-116). Empty drafts never touch alt or provenance.
		$draft        = self::normalize_alt_text_draft( $data['alt_text_draft'] ?? null );
		$existing_alt = get_post_meta( $media_id, self::ALT_TEXT_META_KEY, true );
		$existing_alt = is_string( $existing_alt ) ? $existing_alt : '';
		// Identity keys only for the idempotence compare; draft is measured data
		// stamped when the alt meta is written, or healed on a force no-op (BR-108).
		$provenance   = $this->build_generated_provenance( $data, $draft );

		if ( '' !== trim( $existing_alt ) && ! $force ) {
			$data['alt_text_write'] = array(
				'status'               => 'skipped_existing_alt',
				'existing_alt_present' => true,
			);
			$response->set_data( $data );
			return $response;
		}

		// BR-104: agree with CLI (`skipped_empty_alt_text`) and bulk
		// (`skipped_no_draft`) — never write '' over a human alt, never stamp
		// provenance claiming a draft that was not applied. Check after the
		// existing-alt guard so force=false + existing still reports
		// skipped_existing_alt (CLI order).
		if ( '' === $draft ) {
			$data['alt_text_write'] = array(
				'status'               => 'skipped_empty_alt_text',
				'existing_alt_present' => '' !== trim( $existing_alt ),
			);
			$response->set_data( $data );
			return $response;
		}

		$existing_provenance = get_post_meta( $media_id, self::PROVENANCE_META_KEY, true );
		if (
			$force
			&& $draft === $existing_alt
			&& $this->matches_generated_provenance( $existing_provenance, $provenance )
		) {
			// No-op: alt already equals this draft under matching model identity.
			// Identity keys stay put; heal alt_text_draft when missing/stale so
			// the audit trail matches the confirmed draft (BR-108 / RLSE-05).
			// Do not re-stamp generated_at or rewrite the whole envelope.
			$this->heal_provenance_alt_text_draft( $media_id, $existing_provenance, $draft );
			$data['alt_text_write'] = array(
				'status'               => 'forced_overwrite',
				'existing_alt_present' => true,
			);
			$response->set_data( $data );
			return $response;
		}

		update_post_meta( $media_id, self::ALT_TEXT_META_KEY, $draft );
		update_post_meta( $media_id, self::PROVENANCE_META_KEY, $provenance );

		$write_result = array(
			'status'               => '' !== trim( $existing_alt ) ? 'forced_overwrite' : 'written',
			'existing_alt_present' => '' !== trim( $existing_alt ),
		);

		$description_write = $this->maybe_write_long_description( $data, $media_id, $force );
		if ( null !== $description_write ) {
			$write_result['description_write'] = $description_write;
		}

		$data['alt_text_write'] = $write_result;
		$response->set_data( $data );
		return $response;
	}

	/**
	 * BR-108: on a force no-op (alt already equals draft under matching model
	 * identity), upsert `alt_text_draft` when it is missing or unequal. Pre-wave
	 * envelopes lack the key entirely — a naive match on the draft would break
	 * their no-op — so identity matching stays draft-free and this heal closes
	 * the gap without rewriting generated_at or other identity fields.
	 *
	 * @param mixed  $existing_provenance Stored `_acx_description_provenance`.
	 * @param string $draft               Incoming normalized draft (non-empty).
	 */
	private function heal_provenance_alt_text_draft( int $media_id, mixed $existing_provenance, string $draft ): void {
		if ( ! is_array( $existing_provenance ) ) {
			return;
		}

		$stored = $existing_provenance['alt_text_draft'] ?? null;
		if ( is_string( $stored ) && $stored === $draft ) {
			return;
		}

		$healed                    = $existing_provenance;
		$healed['alt_text_draft']  = $draft;
		update_post_meta( $media_id, self::PROVENANCE_META_KEY, $healed );
	}

	/**
	 * ALTQ-1: when the operator opted into `alt_plus_description` and the
	 * backend produced the optional `alt_text_long`, mirror it to the
	 * attachment description (`post_content`). Returns the write status, or
	 * null when `acx_alt_style` resolves to `alt_only` (default) so the
	 * `alt_text_write` payload stays byte-identical to pre-ALTQ-1 behavior.
	 * Invalid stored option values degrade to `alt_only` via
	 * {@see AltStyle::normalize()}. Runs only on the alt-write path — a
	 * skipped alt write (human-authored alt present, no force) never touches
	 * the description either.
	 *
	 * @param array<string,mixed> $data
	 */
	private function maybe_write_long_description( array $data, int $media_id, bool $force ): ?string {
		if ( AltStyle::ALT_PLUS_DESCRIPTION !== AltStyle::current() ) {
			return null;
		}

		$long = is_string( $data['alt_text_long'] ?? null ) ? trim( $data['alt_text_long'] ) : '';
		if ( '' === $long ) {
			return 'skipped_no_long_text';
		}

		$attachment           = get_post( $media_id );
		$existing_description = is_object( $attachment ) && is_string( $attachment->post_content ?? null )
			? trim( $attachment->post_content )
			: '';

		if ( '' !== $existing_description && ! $force ) {
			return 'skipped_existing_description';
		}

		wp_update_post(
			array(
				'ID'           => $media_id,
				'post_content' => $long,
			)
		);

		return '' !== $existing_description ? 'forced_overwrite' : 'written';
	}

	/**
	 * @param mixed               $existing
	 * @param array<string,mixed> $incoming
	 */
	private function matches_generated_provenance( mixed $existing, array $incoming ): bool {
		if ( ! is_array( $existing ) ) {
			return false;
		}

		foreach ( array( 'adapter', 'model_id', 'model_version', 'prompt_or_task_version', 'image_hash', 'context_hash' ) as $key ) {
			if ( ( $existing[ $key ] ?? null ) !== ( $incoming[ $key ] ?? null ) ) {
				return false;
			}
		}

		return ( $existing['backend_result_id'] ?? null ) === ( $incoming['backend_result_id'] ?? null );
	}

	/**
	 * Build the provenance envelope for a generated alt write.
	 *
	 * `$alt_text_draft` is the exact string the caller is about to persist to
	 * `_wp_attachment_image_alt` — measured data, not re-derived here [rg-015].
	 * History reads this key (via `resolve_generated_alt_text`) to populate the
	 * Generated-alt column. Callers must not persist this full envelope unless
	 * the alt write actually happens (`skipped_existing_alt` /
	 * `skipped_empty_alt_text` never write). A force no-op may heal only the
	 * `alt_text_draft` key on the *existing* envelope (BR-108) without calling
	 * this builder for a full restamp.
	 *
	 * @param array<string,mixed> $data
	 * @param string              $alt_text_draft Exact draft written (or about to be written) to alt meta.
	 *
	 * @return array<string,mixed>
	 */
	private function build_generated_provenance( array $data, string $alt_text_draft ): array {
		$provenance = array(
			'adapter'                => $data['adapter'],
			'model_id'               => $data['model_id'],
			'model_version'          => $data['model_version'],
			'prompt_or_task_version' => $data['prompt_or_task_version'],
			'image_hash'             => $data['image_hash'],
			'context_hash'           => $data['context_hash'],
			'generated_at'           => gmdate( 'c' ),
			// Exact string written to alt — history's Generated-alt column source.
			'alt_text_draft'         => $alt_text_draft,
		);

		if ( array_key_exists( 'backend_result_id', $data ) ) {
			$provenance['backend_result_id'] = $data['backend_result_id'];
		} elseif ( array_key_exists( 'result_id', $data ) ) {
			$provenance['backend_result_id'] = $data['result_id'];
		}

		return $provenance;
	}

	private function payload_too_large_error( int $media_id, int $size_bytes ): WP_Error {
		return new WP_Error(
			'describe_payload_too_large',
			sprintf(
				'Image for media_id=%d is %d bytes, exceeding the %d-byte cap.',
				$media_id,
				$size_bytes,
				self::MULTIPART_MAX_BYTES
			),
			array( 'status' => 413 )
		);
	}

	private function record_success_from_response( int $media_id, WP_REST_Response $response, float $started_at ): void {
		$data                = $response->get_data();
		$provider_disclosure = is_array( $data['provider_disclosure'] ?? null ) ? $data['provider_disclosure'] : array();

		$this->budget_service->record_success(
			$media_id,
			is_string( $data['adapter'] ?? null ) ? $data['adapter'] : 'description',
			is_string( $provider_disclosure['provider'] ?? null ) ? $provider_disclosure['provider'] : 'service',
			isset( $data['duration_ms'] ) ? max( 0, (int) $data['duration_ms'] ) : $this->elapsed_ms( $started_at ),
			(bool) ( $data['cached'] ?? false ),
			'drafted'
		);
	}

	private function record_error_from_response( int $media_id, WP_REST_Response $response ): void {
		$status  = $response->get_status();
		$data    = $response->get_data();
		$message = sprintf( 'Upstream description request failed with HTTP %d.', $status );
		if ( is_array( $data ) && is_string( $data['detail'] ?? null ) && '' !== $data['detail'] ) {
			$message = $data['detail'];
		}

		$this->budget_service->record_error(
			$media_id,
			'description',
			'service',
			sprintf( 'upstream_http_%d', $status ),
			$message,
			$status >= 500 || 429 === $status,
			'backend'
		);
	}

	private function record_error_from_wp_error( int $media_id, WP_Error $error, string $source, bool $retryable ): void {
		$this->budget_service->record_error(
			$media_id,
			'description',
			'service',
			(string) $error->get_error_code(),
			$error->get_error_message(),
			$retryable,
			$source
		);
	}

	private function elapsed_ms( float $started_at ): int {
		return max( 0, (int) round( ( microtime( true ) - $started_at ) * 1000 ) );
	}

	private function invalid_envelope_error( int $media_id, string $reason ): WP_Error {
		Telemetry::log_line(
			sprintf( '[acx] describe media_id=%d invalid backend envelope: %s', $media_id, $reason )
		);
		return new WP_Error(
			'invalid_description_envelope',
			sprintf( 'Backend describe response for media_id=%d was malformed: %s.', $media_id, $reason ),
			array( 'status' => 502 )
		);
	}

	/**
	 * @return array<string,mixed>
	 */
	private function build_context_pack( int $media_id, string $path ): array {
		$attachment = get_post( $media_id );
		$parent     = $this->get_public_parent_post( $attachment );
		$context    = array(
			'attachment' => $this->non_empty_fields(
				array(
					'title'       => $this->bounded_string( is_object( $attachment ) && isset( $attachment->post_title ) ? $attachment->post_title : null, 160 ),
					'caption'     => $this->bounded_string( is_object( $attachment ) && isset( $attachment->post_excerpt ) ? $attachment->post_excerpt : null, 500 ),
					'description' => $this->bounded_string( is_object( $attachment ) && isset( $attachment->post_content ) ? $attachment->post_content : null, 1000 ),
					'alt_text'    => $this->bounded_string( get_post_meta( $media_id, '_wp_attachment_image_alt', true ), 500 ),
					'filename'    => $this->bounded_string( basename( $path ), 255 ),
				)
			),
			'identity'   => $this->build_identity_context( $media_id ),
		);

		if ( null !== $parent ) {
			$context['post'] = $this->non_empty_fields(
				array(
					'title'     => $this->bounded_string( $parent->post_title ?? null, 200 ),
					'excerpt'   => $this->bounded_string( $parent->post_excerpt ?? null, 1000 ),
					'post_type' => $this->bounded_string( $parent->post_type ?? null, 64 ),
					'status'    => $this->bounded_string( $parent->post_status ?? null, 32 ),
				)
			);

			if ( isset( $parent->ID ) ) {
				$terms = $this->collect_taxonomy_terms( (int) $parent->ID );
				if ( array() !== $terms ) {
					$context['taxonomy_terms'] = $terms;
				}

				if ( 'product' === (string) ( $parent->post_type ?? '' ) ) {
					$context['product'] = $this->non_empty_fields(
						array(
							'name'  => $this->bounded_string( $parent->post_title ?? null, 200 ),
							'sku'   => $this->bounded_string( get_post_meta( (int) $parent->ID, '_sku', true ), 120 ),
							'price' => $this->bounded_string( get_post_meta( (int) $parent->ID, '_price', true ), 64 ),
						)
					);
				}
			}
		}

		return array_filter(
			$context,
			static fn ( array $value ): bool => array() !== $value
		);
	}

	private function get_public_parent_post( mixed $attachment ): ?object {
		$parent_id = is_object( $attachment ) && isset( $attachment->post_parent ) ? absint( $attachment->post_parent ) : 0;
		if ( $parent_id <= 0 ) {
			return null;
		}

		$parent = get_post( $parent_id );
		if ( ! is_object( $parent ) || 'publish' !== (string) ( $parent->post_status ?? '' ) ) {
			return null;
		}

		return $parent;
	}

	/**
	 * @return array<int,array<string,string>>
	 */
	private function collect_taxonomy_terms( int $object_id ): array {
		$terms = array();
		foreach ( array( 'category', 'post_tag', 'product_cat', 'product_tag' ) as $taxonomy ) {
			$result = wp_get_object_terms( $object_id, $taxonomy );
			if ( is_wp_error( $result ) || ! is_array( $result ) ) {
				continue;
			}

			foreach ( $result as $term ) {
				if ( ! is_object( $term ) || ! isset( $term->name, $term->taxonomy ) ) {
					continue;
				}

				$terms[] = $this->non_empty_fields(
					array(
						'taxonomy' => $this->bounded_string( $term->taxonomy, 64 ),
						'name'     => $this->bounded_string( $term->name, 120 ),
						'slug'     => $this->bounded_string( $term->slug ?? null, 120 ),
					)
				);
			}
		}

		return array_slice( array_values( array_filter( $terms ) ), 0, 20 );
	}


	private function build_identity_context( int $media_id ): array {
		$tenant_id           = $this->host->get_tenant_id();
		$person_naming       = $this->person_naming_policy_allows() ? 'allowed' : 'disabled';
		$rows                = $this->identity_members_repository->list_for_media_ids( $tenant_id, array( $media_id ) );
		$confirmed_identities = array();
		$machine_only_count  = 0;

		foreach ( $rows as $row ) {
			if ( ! is_array( $row ) ) {
				continue;
			}

			// Only an assigned roster person (p.name, exposed separately as
			// `person_name`) may be named — never the COALESCE'd `cluster_label`,
			// which falls back to the machine cluster label `c.label` when the
			// cluster is confirmed but has no person assigned (dismissed /
			// person-dissociated). Gating on that fallback would leak a machine
			// label as a roster-confirmed name.
			$person_name = trim( (string) ( $row['person_name'] ?? '' ) );
			if ( $this->is_truthy_flag( $row['is_user_confirmed'] ?? false ) && '' !== $person_name ) {
				$confirmed_identities[] = $this->non_empty_fields(
					array(
						'name'        => $person_name,
						'identity_id' => trim( (string) ( $row['identity_uuid'] ?? '' ) ),
						'cluster_id'  => trim( (string) ( $row['cluster_uuid'] ?? '' ) ),
						'source'      => 'roster_confirmed',
					)
				);
				continue;
			}

			++$machine_only_count;
		}

		// Review reasons for unnamed faces are independent of whether a confirmed
		// identity is also present: a confirmed person can share an image with
		// unconfirmed/machine-only faces that still need review.
		$review_reasons = array();
		if ( 'disabled' === $person_naming && ( array() !== $confirmed_identities || $machine_only_count > 0 ) ) {
			$review_reasons[] = 'person_naming_policy_disabled';
			$confirmed_identities = array();
		} elseif ( $machine_only_count > 1 ) {
			$review_reasons[] = 'identity_ambiguous';
		} elseif ( 1 === $machine_only_count ) {
			$review_reasons[] = 'identity_unconfirmed';
		}

		return array(
			'policy'         => array( 'person_naming' => $person_naming ),
			'identities'     => $confirmed_identities,
			'review_reasons' => $review_reasons,
		);
	}

	private function person_naming_policy_allows(): bool {
		return $this->is_truthy_flag( get_option( 'acx_description_allow_person_names', false ) );
	}

	private function is_truthy_flag( mixed $value ): bool {
		return true === $value || 1 === $value || '1' === $value || 'true' === $value;
	}

	/**
	 * @param array<string,?string> $fields
	 * @return array<string,string>
	 */
	private function non_empty_fields( array $fields ): array {
		return array_filter(
			$fields,
			static fn ( ?string $value ): bool => null !== $value && '' !== trim( $value )
		);
	}

	private function bounded_string( mixed $value, int $max_length ): ?string {
		if ( ! is_string( $value ) && ! is_numeric( $value ) ) {
			return null;
		}

		$value = trim( (string) $value );
		if ( '' === $value ) {
			return null;
		}

		if ( function_exists( 'mb_substr' ) ) {
			return mb_substr( $value, 0, $max_length, 'UTF-8' );
		}

		if ( preg_match( '/^.{0,' . $max_length . '}/us', $value, $matches ) ) {
			return $matches[0];
		}

		return $value;
	}

	private function resolve_image_mime_type( string $path, int $media_id ): string {
		if ( function_exists( 'wp_check_filetype' ) ) {
			$detected = wp_check_filetype( $path );
			if ( is_array( $detected ) && ! empty( $detected['type'] ) ) {
				return (string) $detected['type'];
			}
		}
		if ( isset( $GLOBALS['__ac_attachment_mimes'][ $media_id ] ) ) {
			return (string) $GLOBALS['__ac_attachment_mimes'][ $media_id ];
		}
		$extension = strtolower( pathinfo( $path, PATHINFO_EXTENSION ) );
		switch ( $extension ) {
			case 'jpg':
			case 'jpeg':
				return 'image/jpeg';
			case 'png':
				return 'image/png';
			case 'webp':
				return 'image/webp';
			default:
				return 'application/octet-stream';
		}
	}
}
