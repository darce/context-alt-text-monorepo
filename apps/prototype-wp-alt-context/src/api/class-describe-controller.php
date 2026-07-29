<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/interface-describe-host.php';
require_once __DIR__ . '/services/class-description-candidate-service.php';
require_once __DIR__ . '/services/class-describe-media-service.php';
require_once __DIR__ . '/services/class-description-history-service.php';

use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Api\Services\DescribeMediaService;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function apply_filters;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function basename;
use function count;
use function file_get_contents;
use function filesize;
use function get_attached_file;
use function is_array;
use function is_int;
use function is_readable;
use function is_string;
use function is_wp_error;
use function max;
use function pathinfo;
use function register_rest_route;
use function sanitize_text_field;
use function sprintf;
use function strlen;
use function strtolower;
use function wp_check_filetype;
use function wp_json_encode;

use const PATHINFO_EXTENSION;

/**
 * E19-1 S6: WordPress `POST /acx/v1/recognition/describe`. A single-image
 * describe proxy that reuses the recognition auth/multipart/circuit transport
 * but targets the new backend `/scene/describe/multipart` route. Separate from
 * the wire-locked `/recognition/analyze` surface (PDS-26).
 */
class DescribeController extends AbstractRecognitionProxyController implements DescribeHostInterface {
	/**
	 * Default per-run media-id cap. Filterable via `acx_describe_run_max_items`.
	 * MUST be kept aligned with the backend `ACX_DESCRIBE_RUN_MAX_ITEMS` env var
	 * (backend default 200): the backend rejects runs above its own cap, so a WP
	 * value above the backend value would surface a raw 4xx instead of this clean
	 * 400.
	 */
	private const DESCRIBE_RUN_MAX_MEDIA_IDS_DEFAULT = 200;

	/**
	 * Default aggregate raw-bytes cap for a bulk describe run. Filterable via
	 * `acx_describe_run_max_body_bytes`. The backend `/scene/describe/run` route
	 * is not behind the single-image UploadSizeLimitMiddleware, so bound the
	 * aggregate raw-bytes payload here to protect proxy memory (raw image bytes
	 * checked incrementally before each read).
	 */
	private const DESCRIBE_RUN_MULTIPART_MAX_BYTES_DEFAULT = 200 * 1024 * 1024;

	private DescribeMediaService $describe_media_service;
	private DescriptionCandidateService $description_candidate_service;
	private DescriptionHistoryService $description_history_service;

	public function __construct( ?DescribeMediaService $describe_media_service = null, ?DescriptionCandidateService $description_candidate_service = null, ?DescriptionHistoryService $description_history_service = null ) {
		$this->describe_media_service = $describe_media_service ?? new DescribeMediaService( $this );
		$this->description_candidate_service = $description_candidate_service ?? new DescriptionCandidateService();
		$this->description_history_service = $description_history_service ?? new DescriptionHistoryService();
	}

	public function get_tenant_id(): string {
		return parent::get_tenant_id();
	}

	/**
	 * @param array<string,mixed> $body
	 * @param array<string,mixed> $query
	 */
	public function proxy_recognition_request(
		string $method,
		string $path,
		array $body = array(),
		array $query = array(),
		string $request_class = 'auto',
		string $body_kind = 'json',
		?int $max_body_bytes = null
	): WP_REST_Response|WP_Error {
		return $this->proxy_request( $method, $path, $body, $query, $request_class, $body_kind, $max_body_bytes );
	}

	public function is_proxy_unavailable( WP_REST_Response|WP_Error $response ): bool {
		return parent::is_proxy_unavailable( $response );
	}

	public function register_routes(): void {
		register_rest_route(
			'acx/v1',
			'/recognition/describe',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'describe_media' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_id' => array(
						'type'        => 'integer',
						'required'    => true,
						'description' => 'Attachment id to describe (single image).',
					),
					'write_alt' => array(
						'type'        => 'boolean',
						'required'    => false,
						'default'     => false,
						'description' => 'Persist the generated alt text to the attachment when policy allows.',
					),
					'force'     => array(
						'type'        => 'boolean',
						'required'    => false,
						'default'     => false,
						'description' => 'Overwrite existing attachment alt text when write_alt is true.',
					),
				),
			)
		);
		register_rest_route(
			'acx/v1',
			'/recognition/describe/candidates',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'list_description_candidates' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'limit'  => array(
						'type'        => 'integer',
						'required'    => false,
						'default'     => 50,
						'description' => 'Maximum candidate rows to return.',
					),
					'offset' => array(
						'type'        => 'integer',
						'required'    => false,
						'default'     => 0,
						'description' => 'Candidate offset after filtering.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/history',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_description_history' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'limit' => array(
						'type'        => 'integer',
						'default'     => 50,
						'description' => 'Maximum number of description history rows to return.',
					),
					'offset' => array(
						'type'        => 'integer',
						'default'     => 0,
						'description' => 'Description history row offset.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/history/(?P<media_id>\d+)/correction',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'correct_description_history_item' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_id' => array(
						'type'        => 'integer',
						'required'    => true,
						'description' => 'Attachment id to correct.',
					),
					'alt_text' => array(
						'type'        => 'string',
						'required'    => true,
						'description' => 'Human-corrected alt text.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'submit_describe_run' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'media_ids' => array(
						'type'        => 'array',
						'required'    => true,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Attachment ids to describe in bulk.',
					),
				),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_describe_run_status' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)/cancel',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'cancel_describe_run' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)/items',
			array(
				'methods'             => 'GET',
				'callback'            => array( $this, 'get_describe_run_items' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
			)
		);

		register_rest_route(
			'acx/v1',
			'/recognition/describe/runs/(?P<run_id>[a-f0-9-]+)/apply',
			array(
				'methods'             => 'POST',
				'callback'            => array( $this, 'apply_describe_run_drafts' ),
				'permission_callback' => array( $this, 'can_manage_recognition' ),
				'args'                => array(
					'overwrite_media_ids' => array(
						'type'        => 'array',
						'required'    => false,
						'items'       => array( 'type' => 'integer' ),
						'description' => 'Media ids whose existing alt text the operator explicitly chose to overwrite.',
					),
				),
			)
		);
	}

	public function describe_media( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		return $this->describe_media_service->describe_media( $request );
	}

	public function list_description_candidates( WP_REST_Request $request ): WP_REST_Response {
		return new WP_REST_Response(
			$this->description_candidate_service->list_missing_alt_candidates(
				(int) $request->get_param( 'limit' ),
				(int) $request->get_param( 'offset' )
			),
			200
		);
	}

	public function get_description_history( WP_REST_Request $request ): WP_REST_Response {
		return new WP_REST_Response(
			$this->description_history_service->list_history(
				absint( $request->get_param( 'limit' ) ?? 50 ),
				absint( $request->get_param( 'offset' ) ?? 0 )
			)
		);
	}

	public function correct_description_history_item( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$result = $this->description_history_service->record_correction(
			absint( $request->get_param( 'media_id' ) ),
			(string) $request->get_param( 'alt_text' )
		);
		if ( is_wp_error( $result ) ) {
			return $result;
		}

		return new WP_REST_Response( $result );
	}

	public function submit_describe_run( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$media_ids = $this->normalize_media_ids( $request->get_param( 'media_ids' ) );
		if ( is_wp_error( $media_ids ) ) {
			return $media_ids;
		}
		if ( array() === $media_ids ) {
			return new WP_Error( 'missing_media_ids', 'Please provide one or more media IDs to describe.', array( 'status' => 400 ) );
		}

		// The browser→WP contract is JSON { media_ids: int[] } — the browser has
		// no image bytes. WP loads each attachment's bytes and forwards a
		// multipart/form-data body to the backend: field `tenant_id`, field
		// `media_ids` (JSON int array as string), and one `image_<media_id>` file
		// part per id. The backend 422s if any media_id lacks an image part, so a
		// file we cannot read fails the whole run fast (400 naming the id) instead
		// of silently dropping it.
		$multipart_body = array(
			'tenant_id' => $this->get_tenant_id(),
			'media_ids' => wp_json_encode( array_values( $media_ids ) ),
		);

		// PHP-01: bound aggregate raw bytes BEFORE loading them. Stat each file
		// and reject on a single-file or running-total overflow so a large run
		// returns a clean 413 instead of OOM-fataling while buffering every
		// attachment in memory.
		$max_body_bytes = $this->describe_run_max_body_bytes();
		$running_total  = 0;
		foreach ( $media_ids as $media_id ) {
			$file_part = $this->load_media_file_part( $media_id, $max_body_bytes, $running_total );
			if ( is_wp_error( $file_part ) ) {
				return $file_part;
			}
			$running_total                          += strlen( $file_part['content'] );
			$multipart_body[ 'image_' . $media_id ]  = $file_part;
		}

		return $this->proxy_recognition_request(
			'POST',
			'/scene/describe/run',
			$multipart_body,
			array(),
			'description',
			'multipart',
			$max_body_bytes
		);
	}

	private function describe_run_max_media_ids(): int {
		$max = (int) apply_filters( 'acx_describe_run_max_items', self::DESCRIBE_RUN_MAX_MEDIA_IDS_DEFAULT );

		return max( 1, $max );
	}

	private function describe_run_max_body_bytes(): int {
		$max = (int) apply_filters( 'acx_describe_run_max_body_bytes', self::DESCRIBE_RUN_MULTIPART_MAX_BYTES_DEFAULT );

		return max( 1, $max );
	}

	public function get_describe_run_status( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}

		// PHP-02: status is polled repeatedly during a long bulk run. The default
		// 'auto'+GET class resolves to `ui_read` (2s + circuit breaker ON), which
		// would trip the SHARED recognition breaker and 503 every recognition
		// endpoint. `post_scan_read` (10s, no breaker) matches the sibling read
		// pattern.
		return $this->proxy_recognition_request(
			'GET',
			sprintf( '/scene/describe/run/%s', $run_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() ),
			'post_scan_read'
		);
	}

	public function cancel_describe_run( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}

		return $this->proxy_recognition_request(
			'DELETE',
			sprintf( '/scene/describe/run/%s', $run_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() )
		);
	}

	/**
	 * WBUX-4 INT-01b: read a completed run's per-item drafts so the operator can
	 * review/apply them. Proxies the backend items endpoint (read class, like
	 * status), then annotates each item with `existing_alt` — a WP-side post-meta
	 * fact the backend cannot know — so the History UI can bucket drafts safe to
	 * auto-apply (no existing alt) from those that would clobber operator text.
	 */
	public function get_describe_run_items( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}

		$response = $this->proxy_recognition_request(
			'GET',
			sprintf( '/scene/describe/run/%s/items', $run_id ),
			array(),
			array( 'tenant_id' => $this->get_tenant_id() ),
			'post_scan_read'
		);

		if ( is_wp_error( $response ) || $this->is_proxy_unavailable( $response ) ) {
			return $response;
		}

		$data = $response->get_data();
		if ( is_array( $data ) && isset( $data['items'] ) && is_array( $data['items'] ) ) {
			// S2-01: prime the post-meta cache in one query for every media_id
			// instead of an uncached get_post_meta() per item (N+1). update_meta_cache
			// is a WP-core optimization; guard so the unit-test harness (no object
			// cache) falls through to direct get_post_meta reads.
			$media_ids = array();
			foreach ( $data['items'] as $item ) {
				$media_id = isset( $item['media_id'] ) ? (int) $item['media_id'] : 0;
				if ( $media_id > 0 ) {
					$media_ids[] = $media_id;
				}
			}
			if ( array() !== $media_ids && function_exists( 'update_meta_cache' ) ) {
				update_meta_cache( 'post', array_values( array_unique( $media_ids ) ) );
			}

			foreach ( $data['items'] as $index => $item ) {
				$media_id      = isset( $item['media_id'] ) ? (int) $item['media_id'] : 0;
				$existing_alt  = trim( (string) get_post_meta( $media_id, '_wp_attachment_image_alt', true ) );
				$item['existing_alt'] = '' !== $existing_alt;
				$data['items'][ $index ] = $item;
			}
			$response->set_data( $data );
		}

		return $response;
	}

	/**
	 * WBUX-4 INT-01c: apply a completed run's drafts to attachment alt text with
	 * a guarded smart default — items with no existing alt are written; items
	 * that already have existing alt text are NEVER clobbered unless their
	 * media_id is in `overwrite_media_ids` (an explicit per-item opt-in mirroring
	 * the single-image `write_alt`+`force` policy), or a verified bulk-partial
	 * recovery marker is present (see below). Items without a draft (failed
	 * describes) are skipped. A run is applyable only once terminal-with-drafts
	 * (status `completed` / `completed_with_errors`); a pending / running / failed /
	 * cancelled run is rejected with a 409 so drafts are never written mid-flight
	 * (S3-03).
	 *
	 * Two-write honesty matches DescriptionHistoryService::record_correction: a
	 * verified alt plus a failed telemetry write is not full success. Bulk cannot
	 * fail the whole response for one item, so partial outcomes land in `partial`
	 * rather than a 500 WP_Error — same contract, multi-item shape. [RLSE-05]
	 *
	 * Response buckets (frontend contract — the History UI reports each honestly):
	 * `applied` (alt + provenance both verified), `partial` (alt landed, provenance
	 * write did not — do not treat as fully applied; history may omit the item),
	 * `skipped_existing` (existing alt guarded), `skipped_no_draft` (failed describe
	 * / empty draft), `skipped_invalid` (media_id is not an attachment post, S3-01),
	 * and `failed` (the alt-text write returned false, S3-02). `applied` keeps its
	 * prior meaning; `partial` is additive. Do not invent envelope fields beyond
	 * what was measured. [rg-015]
	 *
	 * Partial recovery (non-clobber completion): when a prior apply wrote alt but
	 * failed provenance, this path also writes durable evidence —
	 * `_acx_description_provenance_pending` = `{ run_id, draft_hash }` — scoped to
	 * this run and this draft. On a later apply, if `existing_alt` is set and the
	 * operator did not opt into overwrite, the guard falls through **only** when
	 * that marker exists, its `run_id` matches the current run, its `draft_hash`
	 * matches hash(sha256, current draft), stored alt is still byte-identical to
	 * the draft, and provenance is still not an array. Equality of alt to draft
	 * alone is not evidence this system started the write (coincidental operator
	 * text / partial inline correction) and must stay guarded. No marker →
	 * `skipped_existing`, requiring explicit `overwrite_media_ids`. Marker write
	 * failure is fail-closed: no marker means no automatic recovery. [RLSE-05]
	 * [INT-11] [rg-015]
	 */
	public function apply_describe_run_drafts( WP_REST_Request $request ): WP_REST_Response|WP_Error {
		// S3-03: gate on the authoritative run status. The /items endpoint carries
		// only per-item statuses, not a run-level status, so read it from the
		// status endpoint before writing anything.
		$status_response = $this->get_describe_run_status( $request );
		if ( is_wp_error( $status_response ) || $this->is_proxy_unavailable( $status_response ) ) {
			return $status_response;
		}
		// D1-03: is_proxy_unavailable only trips on >=500, so a status-endpoint 404
		// (run id does not exist) would otherwise collapse into the generic 409
		// "current status: unknown" below. Label it honestly as a 404 instead — a
		// missing run is not a non-terminal run. Other 4xx stay fail-closed via the
		// 409 gate.
		if ( 404 === (int) $status_response->get_status() ) {
			return new WP_Error(
				'describe_run_not_found',
				sprintf( 'Describe run %s was not found.', $this->normalize_run_id( $request ) ),
				array( 'status' => 404 )
			);
		}
		$status_data = $status_response->get_data();
		$run_status  = is_array( $status_data ) ? (string) ( $status_data['status'] ?? '' ) : '';
		if ( 'completed' !== $run_status && 'completed_with_errors' !== $run_status ) {
			return new WP_Error(
				'describe_run_not_applicable',
				sprintf(
					'Describe run must be completed before applying drafts (current status: %s).',
					'' === $run_status ? 'unknown' : $run_status
				),
				array( 'status' => 409 )
			);
		}

		$items_response = $this->get_describe_run_items( $request );
		if ( is_wp_error( $items_response ) || $this->is_proxy_unavailable( $items_response ) ) {
			return $items_response;
		}

		$data  = $items_response->get_data();
		$items = ( is_array( $data ) && is_array( $data['items'] ?? null ) ) ? $data['items'] : array();

		// BR-92: bucket exclusivity is per media_id. The backend may (unverified)
		// echo duplicate rows for the same id; without collapse, one occurrence can
		// land in `applied` and a later occurrence of the same id in
		// `skipped_existing`. Keep first-seen positive media_id only.
		$items = $this->normalize_apply_items_by_media_id( $items );

		// S3-05: reject non-positive overwrite ids rather than absint()-coercing a
		// negative id into a positive one (-70 → 70 would opt in the wrong media).
		$overwrite = array();
		foreach ( (array) $request->get_param( 'overwrite_media_ids' ) as $raw_id ) {
			$overwrite_id = (int) $raw_id;
			if ( $overwrite_id > 0 ) {
				$overwrite[ $overwrite_id ] = true;
			}
		}

		$applied          = array();
		$partial          = array();
		$skipped_existing = array();
		$skipped_no_draft = array();
		$skipped_invalid  = array();
		$failed           = array();
		$run_id           = (string) ( $data['run_id'] ?? '' );

		foreach ( $items as $item ) {
			$media_id = isset( $item['media_id'] ) ? (int) $item['media_id'] : 0;
			$draft    = is_string( $item['alt_text_draft'] ?? null ) ? trim( $item['alt_text_draft'] ) : '';

			if ( 0 === $media_id || '' === $draft ) {
				$skipped_no_draft[] = $media_id;
				continue;
			}

			// S3-01: media_id is backend-echoed data that becomes the post meta
			// target — refuse to stamp alt text onto anything that is not an
			// attachment post.
			$post = get_post( $media_id );
			if ( ! is_object( $post ) || 'attachment' !== (string) ( $post->post_type ?? '' ) ) {
				$skipped_invalid[] = $media_id;
				continue;
			}

			if ( ! empty( $item['existing_alt'] ) && ! isset( $overwrite[ $media_id ] ) ) {
				// Non-clobber completion: only when durable evidence proves this
				// system started this write for this run+draft (pending marker).
				// Alt===draft alone is not enough — coincidental operator text must
				// stay guarded. Belt-and-braces: alt still equals draft and
				// provenance is still absent so a stale marker cannot rewrite alt.
				$stored_alt  = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
				$stored_prov = get_post_meta( $media_id, '_acx_description_provenance', true );
				$pending     = get_post_meta( $media_id, '_acx_description_provenance_pending', true );
				$draft_hash  = hash( 'sha256', $draft );
				$is_non_clobber_completion = is_array( $pending )
					&& isset( $pending['run_id'], $pending['draft_hash'] )
					&& (string) $pending['run_id'] === $run_id
					&& (string) $pending['draft_hash'] === $draft_hash
					&& is_string( $stored_alt )
					&& $stored_alt === $draft
					&& ! is_array( $stored_prov );

				if ( ! $is_non_clobber_completion ) {
					$skipped_existing[] = $media_id;
					continue;
				}
			}

			// S3-04: persist a WP-controlled provenance envelope, not the backend
			// blob verbatim — whitelist the same generated-provenance fields the
			// single-image write records, then stamp the bulk-apply origin and the
			// exact draft string written (history's generated-alt resolver).
			$provenance = $this->build_run_apply_provenance( $item['provenance'] ?? null, $run_id, $draft );

			// S3-02: honor the update_post_meta() return. It also returns false when
			// the stored value is byte-identical to $draft (a no-op overwrite);
			// distinguish that from a real failure via a read-back so an unchanged
			// value still counts as applied rather than landing in `failed`.
			$alt_written = update_post_meta( $media_id, '_wp_attachment_image_alt', $draft );
			if ( false === $alt_written ) {
				$current = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
				if ( ! is_string( $current ) || $draft !== $current ) {
					$failed[] = $media_id;
					continue;
				}
			}

			// Provenance is the history-list gate (build_item returns null when
			// neither provenance nor human-edit is an array). Same return-value +
			// full-payload read-back as DescriptionHistoryService::record_correction
			// for human-edit: silent success after a failed telemetry write made
			// bulk apply report "applied" for items history never shows. [RLSE-05]
			// Alt stays written — do not roll back; bucket as partial so the client
			// can reconcile without treating the id as fully applied.
			$prov_written = update_post_meta( $media_id, '_acx_description_provenance', $provenance );
			if ( false === $prov_written ) {
				$current_prov = get_post_meta( $media_id, '_acx_description_provenance', true );
				// Accept only a full-payload no-op (update_post_meta returns false
				// when stored value equals the value being written). Partial key
				// matches would forge applied while history still lacks provenance.
				$prov_ok = is_array( $current_prov ) && $provenance === $current_prov;
				if ( ! $prov_ok ) {
					// Durable evidence this system started the write for this
					// run+draft. Marker write failure is fail-closed: without it
					// the next apply cannot auto-recover (operator uses overwrite).
					update_post_meta(
						$media_id,
						'_acx_description_provenance_pending',
						array(
							'run_id'     => $run_id,
							'draft_hash' => hash( 'sha256', $draft ),
						)
					);
					$partial[] = $media_id;
					continue;
				}
			}

			// Provenance verified — drop any pending recovery marker.
			delete_post_meta( $media_id, '_acx_description_provenance_pending' );
			$applied[] = $media_id;
		}

		return new WP_REST_Response(
			array(
				'run_id'           => $run_id,
				'applied'          => $applied,
				'partial'          => $partial,
				'skipped_existing' => $skipped_existing,
				'skipped_no_draft' => $skipped_no_draft,
				'skipped_invalid'  => $skipped_invalid,
				'failed'           => $failed,
			),
			200
		);
	}

	/**
	 * Collapse apply-item rows by positive-integer media_id, keeping first-seen
	 * order. Duplicate rows for the same id would otherwise be bucketed
	 * independently after earlier writes mutate meta, so one id can appear in
	 * two mutually exclusive response buckets. Non-positive ids are left as-is
	 * (they land in skipped_no_draft / skipped_invalid via the main loop).
	 *
	 * @param array<int,mixed> $items
	 *
	 * @return array<int,mixed>
	 */
	private function normalize_apply_items_by_media_id( array $items ): array {
		$normalized = array();
		$seen       = array();
		foreach ( $items as $item ) {
			if ( ! is_array( $item ) ) {
				continue;
			}
			$media_id = isset( $item['media_id'] ) ? (int) $item['media_id'] : 0;
			if ( $media_id > 0 ) {
				if ( isset( $seen[ $media_id ] ) ) {
					continue;
				}
				$seen[ $media_id ] = true;
			}
			$normalized[] = $item;
		}

		return $normalized;
	}

	/**
	 * S3-04: build the provenance envelope persisted alongside a bulk-applied
	 * draft. Whitelists generated-provenance fields from the backend item
	 * provenance so no arbitrary upstream keys are stored verbatim, stamps the
	 * bulk-apply origin, and records `alt_text_draft` as the exact draft string
	 * written (measured data for history's generated-alt resolver — never left
	 * empty when a draft was applied). `generated_at` is carried through only
	 * when the backend supplied it — never fabricated at apply time.
	 *
	 * @param mixed  $incoming Backend-supplied item provenance (may be null/scalar).
	 * @param string $run_id   Describe-run id stamped onto the envelope.
	 * @param string $draft    Exact alt draft string being written.
	 *
	 * @return array<string,mixed>
	 */
	private function build_run_apply_provenance( mixed $incoming, string $run_id, string $draft ): array {
		$incoming   = is_array( $incoming ) ? $incoming : array();
		$provenance = array();
		foreach ( array( 'adapter', 'model_id', 'model_version', 'prompt_or_task_version', 'image_hash', 'context_hash', 'generated_at', 'backend_result_id', 'alt_text_draft' ) as $key ) {
			if ( array_key_exists( $key, $incoming ) ) {
				$provenance[ $key ] = $incoming[ $key ];
			}
		}

		// Prefer the measured draft we are writing over any backend-supplied key
		// so history's generated-alt resolver sees the same string as the alt.
		$provenance['alt_text_draft'] = $draft;
		$provenance['source']         = 'bulk_describe_run';
		$provenance['run_id']         = $run_id;
		$provenance['applied_at']     = gmdate( 'c' );

		return $provenance;
	}

	/**
	 * Normalize the requested media IDs. Non-positive ids are filtered out and
	 * duplicates are collapsed (first-seen order preserved, PHP-04) so a caller
	 * cannot trigger redundant inference. More than the per-run cap of distinct
	 * ids returns a WP_Error rather than silently truncating — a silent slice
	 * would drop work the caller believes it queued (S5-02). The cap is
	 * filterable via `acx_describe_run_max_items` (PHP-03).
	 *
	 * @return int[]|WP_Error
	 */
	private function normalize_media_ids( mixed $value ): array|WP_Error {
		if ( ! is_array( $value ) ) {
			return array();
		}

		$media_ids = array_values(
			array_unique(
				array_filter(
					array_map( 'absint', $value ),
					static fn (int $media_id): bool => $media_id > 0
				)
			)
		);

		$max_media_ids = $this->describe_run_max_media_ids();
		if ( count( $media_ids ) > $max_media_ids ) {
			return new WP_Error(
				'too_many_media_ids',
				sprintf( 'Please describe at most %d media IDs per run.', $max_media_ids ),
				array( 'status' => 400 )
			);
		}

		return $media_ids;
	}

	/**
	 * Load a single attachment's bytes as a multipart file part for the bulk run
	 * body. Returns a WP_Error (400) naming the failing media_id when the file is
	 * missing, unreadable, or empty — the backend would otherwise 422 the whole
	 * run for a missing `image_<media_id>` part. Returns a WP_Error (413) when the
	 * file alone, or the running body total including it, exceeds $max_body_bytes
	 * — checked on a cheap stat BEFORE reading the bytes into memory (PHP-01).
	 *
	 * @return array{filename:string,content:string,content_type:string}|WP_Error
	 */
	private function load_media_file_part( int $media_id, int $max_body_bytes, int $running_total ): array|WP_Error {
		$path = get_attached_file( $media_id, true );
		if ( ! is_string( $path ) || '' === $path || ! is_readable( $path ) ) {
			return new WP_Error(
				'describe_run_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is missing or not readable.', $media_id ),
				array( 'status' => 400 )
			);
		}

		// Cheap pre-read guard: reject before buffering the file into memory.
		$stat_size = @filesize( $path );
		if ( is_int( $stat_size ) && ( $stat_size > $max_body_bytes || $running_total + $stat_size > $max_body_bytes ) ) {
			return $this->payload_too_large_error( $media_id, $running_total + $stat_size, $max_body_bytes );
		}

		// Bounded read: never buffer more than the remaining body budget (+1 to
		// detect overflow), so a false/stale filesize() cannot defeat the memory
		// cap by falling through to an unbounded read (SRV-01).
		$remaining = $max_body_bytes - $running_total;
		$bytes     = @file_get_contents( $path, false, null, 0, $remaining + 1 );
		if ( false === $bytes || '' === $bytes ) {
			return new WP_Error(
				'describe_run_attachment_unreadable',
				sprintf( 'Attachment file for media_id=%d is empty or unreadable.', $media_id ),
				array( 'status' => 400 )
			);
		}

		// Overflow guard covering the case where filesize() was unavailable
		// (false) or stale versus the bytes actually read.
		if ( strlen( $bytes ) > $remaining ) {
			return $this->payload_too_large_error( $media_id, $running_total + strlen( $bytes ), $max_body_bytes );
		}

		return array(
			'filename'     => basename( $path ),
			'content'      => $bytes,
			'content_type' => $this->resolve_image_mime_type( $path, $media_id ),
		);
	}

	private function payload_too_large_error( int $media_id, int $total_bytes, int $max_body_bytes ): WP_Error {
		return new WP_Error(
			'describe_run_payload_too_large',
			sprintf(
				'describe run payload too large: media_id=%d pushed the run to %d bytes, exceeding the %d-byte cap.',
				$media_id,
				$total_bytes,
				$max_body_bytes
			),
			array( 'status' => 413 )
		);
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

	private function normalize_run_id( WP_REST_Request $request ): string {
		return sanitize_text_field( (string) $request->get_param( 'run_id' ) );
	}
}
