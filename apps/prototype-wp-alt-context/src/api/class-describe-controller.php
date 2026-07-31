<?php

declare(strict_types=1);

namespace AltContext\Api;

require_once __DIR__ . '/interface-recognition-route-controller.php';
require_once __DIR__ . '/class-abstract-recognition-proxy-controller.php';
require_once __DIR__ . '/interface-describe-host.php';
require_once __DIR__ . '/class-alt-text-write-status.php';
require_once __DIR__ . '/services/class-description-candidate-service.php';
require_once __DIR__ . '/services/class-describe-media-service.php';
require_once __DIR__ . '/services/class-description-history-service.php';
require_once __DIR__ . '/services/trait-expects-meta-after-core-transforms.php';
require_once __DIR__ . '/../support/class-telemetry.php';

use AltContext\Api\Services\DescriptionCandidateService;
use AltContext\Api\Services\DescriptionHistoryService;
use AltContext\Api\Services\DescribeMediaService;
use AltContext\Api\Services\ExpectsMetaAfterCoreTransforms;
use AltContext\Support\Telemetry;
use WP_Error;
use WP_REST_Request;
use WP_REST_Response;

use function absint;
use function apply_filters;
use function array_filter;
use function array_fill_keys;
use function array_map;
use function array_slice;
use function array_unique;
use function array_values;
use function asort;
use function basename;
use function count;
use function ctype_digit;
use function delete_option;
use function file_get_contents;
use function filesize;
use function get_attached_file;
use function get_option;
use function is_array;
use function is_int;
use function is_numeric;
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
use function time;
use function update_option;
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
	use ExpectsMetaAfterCoreTransforms;

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

	/**
	 * BR-129 / BR-134: locally recorded media_id set for a describe run, keyed by
	 * run_id. Durable non-autoloaded option (not a transient): apply may happen
	 * well after submit (partial-recovery second apply, long-running runs), so a
	 * cache TTL must not gate authorization. Fail closed when absent — never
	 * fall back to trusting the remote items response. Bounded by a pruned index.
	 */
	private const RUN_MEDIA_IDS_OPTION_PREFIX     = 'acx_describe_run_media_ids_';
	private const RUN_MEDIA_IDS_INDEX_OPTION      = 'acx_describe_run_media_ids_index';
	private const RUN_MEDIA_IDS_MAX_AGE_SECONDS   = 2592000; // 30 days.
	private const RUN_MEDIA_IDS_INDEX_MAX_ENTRIES = 200;
	/**
	 * BR-142: cap eviction may only remove entries older than this floor.
	 * A busy site can churn 200 runs inside a review window; revoking a live
	 * membership to keep the index at 200 is worse than a bounded storage leak.
	 * Age pruning (30d) still hard-caps lifetime.
	 */
	private const RUN_MEDIA_IDS_CAP_EVICTION_MIN_AGE_SECONDS = 604800; // 7 days.

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
					// No schema default: WP_REST_Request::get_param applies defaults,
					// so default=>false would make absent and explicit false
					// indistinguishable and break the un-mark tri-state [A-02].
					// Absent still means "unspecified"; the service treats null as
					// today's prior default-false behaviour — existing clients that
					// omit the flag keep the same outcome.
					'decorative' => array(
						'type'        => 'boolean',
						'required'    => false,
						'description' => 'Tri-state decorative flag: true marks decorative, false un-marks, omit leaves unspecified.',
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
		// Tri-state decorative [A-02]: null when absent (unspecified ≡ prior
		// default-false behaviour), bool when the client sent an explicit value.
		// Do not coalesce absent to false — that collapses un-mark into unspecified.
		$raw_decorative = $request->get_param( 'decorative' );
		$result         = $this->description_history_service->record_correction(
			absint( $request->get_param( 'media_id' ) ),
			(string) $request->get_param( 'alt_text' ),
			null === $raw_decorative ? null : (bool) $raw_decorative
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

		$response = $this->proxy_recognition_request(
			'POST',
			'/scene/describe/run',
			$multipart_body,
			array(),
			'description',
			'multipart',
			$max_body_bytes
		);

		// BR-129 / BR-134: record the WP-side submitted media_id set keyed by
		// run_id so apply can refuse remote-chosen ids. Only on a successful
		// submit that returns a run_id — without a local record, apply fails
		// closed. The run is already accepted upstream; if the durable write
		// fails, report that apply will be impossible rather than a false 202.
		if ( $response instanceof WP_REST_Response && $response->get_status() < 400 ) {
			$data = $response->get_data();
			if ( is_array( $data ) ) {
				$run_id = isset( $data['run_id'] ) && is_string( $data['run_id'] )
					? sanitize_text_field( $data['run_id'] )
					: '';
				if ( '' !== $run_id ) {
					$stored = $this->store_run_media_ids( $run_id, $media_ids );
					if ( is_wp_error( $stored ) ) {
						return $stored;
					}
				}
			}
		}

		return $response;
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
			// BR-145: reject non-array items before enrichment. Enrichment does
			// isset/assign on each item; a string item TypeError-fatals on PHP 8
			// ("Cannot access offset of type string on string") and never reaches
			// the apply loop's is_array guard. Same 502 contract violation as apply.
			foreach ( $data['items'] as $item ) {
				if ( ! is_array( $item ) ) {
					return new WP_Error(
						'describe_run_items_contract_violation',
						'Describe run items response contained a non-object item.',
						array( 'status' => 502 )
					);
				}
			}

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
				$media_id     = isset( $item['media_id'] ) ? (int) $item['media_id'] : 0;
				$alt_raw      = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
				// Only string meta is "existing alt text"; non-string values are
				// unexpected and must not trigger array-to-string notices.
				$existing_alt = is_string( $alt_raw ) ? trim( $alt_raw ) : '';
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
	 * `skipped_existing` (existing alt guarded, or pre-write CAS saw a concurrent
	 * edit), `skipped_no_draft` (failed describe / empty draft), `skipped_invalid`
	 * (media_id is not an attachment post, S3-01), and `failed` (the alt-text write
	 * returned false, S3-02; or a non-false alt write's read-back diverged from
	 * `expected_meta_after_core_transforms` [R22-BR-03]; or the recovery marker
	 * could not be planted after a provenance failure — no auto-retry path
	 * exists). `applied` keeps its prior meaning; `partial` is additive. Do not
	 * invent envelope fields beyond what was measured. [rg-015]
	 *
	 * Partial recovery (non-clobber completion): when a prior apply wrote alt but
	 * failed provenance, this path also writes durable evidence —
	 * `_acx_description_provenance_pending` = `{ run_id, draft_hash }` where
	 * `draft_hash` is sha256 of the **stored** alt form (post wp_unslash +
	 * sanitize_meta), not the raw draft [R22-BR-01]. On a later apply, if stored
	 * alt is non-empty and the operator did not opt into overwrite, the guard
	 * falls through **only** when that marker is a usable same-draft recovery
	 * marker (verified shape + draft_hash match on stored domain — `run_id` is
	 * intentionally not compared so a foreign-run / single-image / CLI marker for
	 * the same draft remains recoverable [R22-BR-02]), stored alt is still a
	 * string and byte-identical to the expected stored draft, stored provenance
	 * is not already **this run's** envelope, **and** stored provenance does not
	 * already describe the stored alt (`provenance_already_describes_stored_alt`
	 * — foreign provenance that already attributes the current alt must not be
	 * replaced [R23-BR-02]). Equality of alt to draft alone is not evidence this
	 * system started the write (coincidental operator text / partial inline
	 * correction) and must stay guarded. No marker → `skipped_existing`,
	 * requiring explicit `overwrite_media_ids`. Marker write failure is
	 * fail-closed: without a verified marker the item is `failed` (not
	 * `partial`) so the UI does not present a non-recoverable item as retryable.
	 * Every stamped envelope carries an always-present `recovered_from`
	 * descriptor `{ origin, kind, chain }` [R23-BR-20/21/22]: first write /
	 * overwrite use kind `none`; same-run recovery uses kind `same_run`; foreign
	 * marker recovery sets `origin` to the marker owner (verbatim) with `kind`
	 * resolved against MARKER_OWNERS / uuid shape, and an append-only `chain`
	 * so consecutive provenance-write failures still name the true originator.
	 * Foreign model metadata is never invented [R23-BR-08] [rg-015].
	 * [RLSE-05] [INT-11] [rg-015]
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

		// BR-107: stamp and compare from the path run id. The items body may omit
		// run_id (or echo a wrong one); markers and the response must use the path.
		$run_id = $this->normalize_run_id( $request );
		if ( '' === $run_id ) {
			return new WP_Error( 'missing_run_id', 'Run ID is required.', array( 'status' => 400 ) );
		}
		if ( is_array( $data ) && array_key_exists( 'run_id', $data ) ) {
			$body_run_id = (string) $data['run_id'];
			if ( '' !== $body_run_id && $body_run_id !== $run_id ) {
				return new WP_Error(
					'describe_run_id_mismatch',
					sprintf(
						'Items body run_id (%s) does not match path run_id (%s).',
						$body_run_id,
						$run_id
					),
					array( 'status' => 400 )
				);
			}
		}

		// BR-129: fail closed when the local submitted set is missing
		// (never-submitted run_id, pruned record, or storage failure). Never
		// trust the remote items list alone as the write target set.
		$submitted_media_ids = $this->load_run_media_ids( $run_id );
		if ( null === $submitted_media_ids ) {
			return new WP_Error(
				'describe_run_media_ids_unknown',
				sprintf(
					'No locally recorded media_id set for describe run %s; refusing to apply remote items.',
					$run_id
				),
				array( 'status' => 502 )
			);
		}

		// Bound returned item count to the same per-run cap used at submit.
		$max_items = $this->describe_run_max_media_ids();
		if ( count( $items ) > $max_items ) {
			return new WP_Error(
				'describe_run_items_overflow',
				sprintf(
					'Describe run items response exceeded the %d-item cap (received %d).',
					$max_items,
					count( $items )
				),
				array( 'status' => 502 )
			);
		}

		// Strict media_id + membership gate before any write. Contract violations
		// from the remote (coercible junk ids, foreign media_ids) are a 502 for
		// the whole apply — not a silent skip bucket — so an attacker-controlled
		// service cannot partially succeed while smuggling extra targets.
		// Justification for 502 over a new envelope bucket: (1) no new measured
		// fields (rg-015); (2) partial apply would mask the attack; (3) 502 is the
		// established boundary-violation signal for untrusted upstream shape.
		$submitted_lookup = array_fill_keys( $submitted_media_ids, true );
		$validated_items  = array();
		foreach ( $items as $item ) {
			if ( ! is_array( $item ) ) {
				return new WP_Error(
					'describe_run_items_contract_violation',
					'Describe run items response contained a non-object item.',
					array( 'status' => 502 )
				);
			}
			$media_id = $this->parse_strict_positive_int( $item['media_id'] ?? null );
			if ( null === $media_id ) {
				return new WP_Error(
					'describe_run_items_contract_violation',
					'Describe run items response contained a non-strict-positive-integer media_id.',
					array( 'status' => 502 )
				);
			}
			if ( ! isset( $submitted_lookup[ $media_id ] ) ) {
				return new WP_Error(
					'describe_run_items_contract_violation',
					sprintf(
						'Describe run items response referenced media_id %d which was not submitted for run %s.',
						$media_id,
						$run_id
					),
					array( 'status' => 502 )
				);
			}
			$item['media_id']  = $media_id;
			$validated_items[] = $item;
		}

		// BR-92 / BR-106: bucket exclusivity is per media_id. Collapse duplicates,
		// preferring the first row that carries a non-empty draft so a failed
		// null-draft echo before a completed draft does not force skipped_no_draft.
		$items = $this->normalize_apply_items_by_media_id( $validated_items );

		// S3-05: reject non-positive overwrite ids rather than absint()-coercing a
		// negative id into a positive one (-70 → 70 would opt in the wrong media).
		$overwrite = array();
		foreach ( (array) $request->get_param( 'overwrite_media_ids' ) as $raw_id ) {
			$overwrite_id = (int) $raw_id;
			if ( $overwrite_id > 0 ) {
				$overwrite[ $overwrite_id ] = true;
			}
		}

		// Bucket key names live on AltTextWriteStatus::BULK_APPLY_BUCKETS (SPA
		// contract — do not rename). Collect media_ids into that ordered surface.
		$buckets = array_fill_keys( AltTextWriteStatus::BULK_APPLY_BUCKETS, array() );

		foreach ( $items as $item ) {
			// media_id already strict-validated above; cast is identity for ints.
			$media_id = (int) ( $item['media_id'] ?? 0 );
			// Model output is plain text at the write boundary (BR-130 / BR-133):
			// same core alt sanitizer as the single-media write path so bare `<`
			// in prose is entity-encoded (not truncated) and genuine markup is
			// still removed. Recovery marker draft_hash is sha256 of the post
			// wp_unslash+sanitize_meta stored form (hash_for_stored_alt of
			// expected_meta_after_core_transforms), not of this sanitized draft
			// string — backslash-bearing text differs between the two [R22-BR-01]
			// [R23-BR-06].
			$draft = is_string( $item['alt_text_draft'] ?? null )
				? sanitize_text_field( $item['alt_text_draft'] )
				: '';
			// Always-present recovery descriptor. Default: no recovery (first
			// write / overwrite). Non-clobber path replaces via the canonical
			// resolver [R23-BR-20/21/22] [R23-BR-24].
			$recovered_from = DescriptionHistoryService::empty_recovered_from();

			if ( 0 === $media_id || '' === $draft ) {
				$buckets['skipped_no_draft'][] = $media_id;
				continue;
			}

			// S3-01: media_id is backend-echoed data that becomes the post meta
			// target — refuse to stamp alt text onto anything that is not an
			// attachment post.
			$post = get_post( $media_id );
			if ( ! is_object( $post ) || 'attachment' !== (string) ( $post->post_type ?? '' ) ) {
				$buckets['skipped_invalid'][] = $media_id;
				continue;
			}

			// Decision-time alt snapshot (fresh read — not the items-endpoint
			// existing_alt boolean, which can lag an in-flight media-library edit).
			$stored_alt_raw = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
			$decision_alt   = $stored_alt_raw;
			// What update_metadata() will store for this draft (unslash then
			// sanitize_meta). Stored alt and recovery comparisons must use this,
			// not the raw draft string — a backslash-bearing or filter-sanitized
			// draft never equals its stored form byte-for-byte (BR-17 / F-15R).
			$expected_stored_alt = $this->expected_meta_after_core_transforms( '_wp_attachment_image_alt', $draft );

			// Non-string alt meta is unexpected; never treat it as empty and never
			// unlock recovery via the string-equality conjunct (BR-119).
			if ( ! is_string( $stored_alt_raw ) ) {
				if ( ! isset( $overwrite[ $media_id ] ) ) {
					$pending = get_post_meta( $media_id, '_acx_description_provenance_pending', true );
					if ( is_array( $pending )
						&& isset( $pending['run_id'] )
						&& (string) $pending['run_id'] === $run_id
					) {
						// Alt type diverged from a string draft — drop this run's marker.
						// R21-BR-10: delete unchecked. Survivor is soft: bucket is
						// already skipped_existing; a zombie owned by this run may
						// linger until a later verified write clears it. Failing the
						// skip would clobber the non-clobber decision.
						delete_post_meta( $media_id, '_acx_description_provenance_pending' );
					}
					$buckets['skipped_existing'][] = $media_id;
					continue;
				}
			} else {
				$has_existing = '' !== trim( $stored_alt_raw );

				if ( $has_existing && ! isset( $overwrite[ $media_id ] ) ) {
					// Non-clobber completion: durable same-draft marker proves the
					// system started this write for this draft (pending marker).
					// Alt===draft alone is not enough — coincidental operator text must
					// stay guarded. Marker ownership (run_id) is irrelevant: a foreign
					// bulk / single-image / CLI marker for the same stored draft is
					// recovery evidence; re-apply must complete provenance [R22-BR-02].
					// draft_hash domain is the stored form [R22-BR-01] (BR-126 / BR-17).
					// Completeness leg [R23-BR-02]: a stored provenance envelope that
					// already describes the stored alt is finished work — do not
					// re-stamp run_id/applied_at. Empty/non-array provenance (true
					// partial) and provenance naming a different draft (stale
					// envelope) still unlock recovery.
					$stored_prov = get_post_meta( $media_id, '_acx_description_provenance', true );
					$pending     = get_post_meta( $media_id, '_acx_description_provenance_pending', true );
					$expected_stored_alt_str = is_string( $expected_stored_alt )
						? $expected_stored_alt
						: (string) $expected_stored_alt;
					$prov_is_this_run = is_array( $stored_prov )
						&& isset( $stored_prov['run_id'] )
						&& (string) $stored_prov['run_id'] === $run_id;
					// $stored_alt_raw is string here (non-string branch returns above).
					// Compare against the value WP stores, not the raw draft (BR-17).
					$is_non_clobber_completion = DescriptionHistoryService::is_usable_pending_marker_for_draft(
						$pending,
						$expected_stored_alt_str
					)
						&& $stored_alt_raw === $expected_stored_alt
						&& ! $prov_is_this_run
						&& ! $this->provenance_already_describes_stored_alt( $stored_prov, $stored_alt_raw );

					if ( ! $is_non_clobber_completion ) {
						// BR-114 / R23-BR-05 / R23-BR-18: drop orphaned markers owned
						// by this run when recovery is rejected because provenance
						// is already this run's complete envelope, or the own-run
						// marker is not live recovery evidence for the currently
						// stored alt (stale draft_hash). Markers for other runs stay
						// (foreign same-draft markers recover above; foreign
						// mismatched markers remain for their owner).
						//
						// R23-BR-18: do NOT drop on alt_diverged alone. A live
						// own-run marker for stored alt S (true partial) must
						// survive when this apply's draft D ≠ S — the marker still
						// names the run that owns the in-flight gap. Clearing it
						// here made completion unmatchable. Dead evidence is still
						// collected via the stale-for-stored-alt leg; alt_diverged
						// with a live marker is skip_existing only (no wipe).
						// Live own-run markers for the stored alt are the
						// true-partial recovery evidence and are preserved.
						//
						// R23-BR-19: staleness is a property of a specific run —
						// identity (marker.run_id === applying run) and content
						// liveness (draft_hash vs stored alt) are one predicate.
						// Judging content alone would treat a foreign marker's
						// draft_hash as this run's clock.
						if ( $prov_is_this_run
							&& is_array( $pending )
							&& isset( $pending['run_id'] )
							&& (string) $pending['run_id'] === $run_id
						) {
							// R21-BR-10: delete unchecked. History already lists via
							// provenance so a survivor is redundant.
							delete_post_meta( $media_id, '_acx_description_provenance_pending' );
						} elseif ( DescriptionHistoryService::is_stale_own_run_marker_for_alt(
							$pending,
							$stored_alt_raw,
							$run_id
						) ) {
							// R21-BR-10: delete unchecked. Own-run marker is dead
							// evidence for this run and must not remain as a
							// re-stamp key [R23-BR-05].
							delete_post_meta( $media_id, '_acx_description_provenance_pending' );
						}
						$buckets['skipped_existing'][] = $media_id;
						continue;
					}

					// Recovery unlocked. Attribute the originating owner via the
					// canonical resolver [R23-BR-24] [R23-BR-08] [R23-BR-20] —
					// carry any prior envelope chain so consecutive failures keep
					// the true originator [rg-015].
					$prior_recovered = null;
					if ( is_array( $stored_prov ) && isset( $stored_prov['recovered_from'] ) && is_array( $stored_prov['recovered_from'] ) ) {
						$prior_recovered = $stored_prov['recovered_from'];
					}
					$recovered_from = DescriptionHistoryService::resolve_recovery_descriptor(
						$pending,
						$run_id,
						$prior_recovered
					);
				}
			}

			// S3-04: persist a WP-controlled provenance envelope, not the backend
			// blob verbatim — whitelist the same generated-provenance fields the
			// single-image write records, then stamp the bulk-apply origin and the
			// exact draft string written (history's generated-alt resolver).
			$provenance = $this->build_run_apply_provenance(
				$item['provenance'] ?? null,
				$run_id,
				$draft,
				$recovered_from
			);

			// BR-115: compare-and-swap — re-read immediately before the write and
			// abort if alt diverged from the decision-time snapshot. Preserves a
			// concurrent media-library edit; does not claim a lock.
			$pre_write_raw = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
			if ( $pre_write_raw !== $decision_alt ) {
				$buckets['skipped_existing'][] = $media_id;
				continue;
			}

			// S3-02 / WBUX-5-R16-BR-10 / R22-BR-03: always read alt back and
			// compare against the shared post-transform expectation (F-15R /
			// BR-17). A non-false accept that persists a divergent value must
			// not bucket as applied. No-op false returns still succeed when
			// storage already equals the expectation.
			update_post_meta( $media_id, '_wp_attachment_image_alt', $draft );
			$current = get_post_meta( $media_id, '_wp_attachment_image_alt', true );
			$alt_ok  = is_string( $current ) && $expected_stored_alt === $current;
			if ( ! $alt_ok ) {
				$buckets['failed'][] = $media_id;
				continue;
			}

			// Invariant: non-empty alt and acx_alt_decorative must not coexist.
			// Sibling writer: DescriptionHistoryService::record_correction self-heals
			// the same way after a verified non-empty alt. CAS above only compares
			// alt, so an operator can plant the marker after the run was created
			// (alt still '') and the write still proceeds — clear here so the bulk
			// path does not leave the self-contradictory pair on disk. [A-05]
			// Only after $alt_ok, only when verified stored alt is non-empty.
			// [INT-09] clear-failure is a partial: alt landed, secondary durable
			// write did not — same bucket used when provenance fails after a
			// verified alt. BULK_APPLY_BUCKETS already exposes `partial`; sibling
			// record_correction returns description_correction_partial for the
			// byte-identical fault. Continue provenance write so history still
			// lists the item; bucket as partial at the end (not applied).
			$decorative_clear_failed = false;
			if ( '' !== trim( $current ) ) {
				delete_post_meta( $media_id, 'acx_alt_decorative' );
				// [DATA-14] read the marker back; do not trust delete_post_meta.
				$decorative_after_clear = get_post_meta( $media_id, 'acx_alt_decorative', true );
				if ( is_string( $decorative_after_clear ) && '1' === $decorative_after_clear ) {
					$decorative_clear_failed = true;
					Telemetry::log_line(
						sprintf(
							'[acx] describe run apply: acx_alt_decorative clear failed after verified non-empty alt for media_id=%d run_id=%s; item remains on apply path',
							$media_id,
							$run_id
						)
					);
				}
			}

			// Provenance is the history-list gate (build_item returns null when
			// neither provenance nor human-edit is an array). Same return-value +
			// full-payload read-back as DescriptionHistoryService::record_correction
			// for human-edit: silent success after a failed telemetry write made
			// bulk apply report "applied" for items history never shows. [RLSE-05]
			// Shared post-transform model (F-15R / BR-17), not unslash-only.
			//
			// R21-BR-04: always read back provenance. A non-false accept may still
			// persist a divergent array — trusting the return alone would delete
			// the marker and hide a real gap.
			//
			// R21-BR-09: when provenance (or the subsequent marker plant) fails,
			// the alt already landed above and is NOT rolled back. The id is
			// bucketed `failed` only when no usable same-draft recovery marker
			// is present (auto-recovery impossible); otherwise `partial`. There
			// is no wire bucket for "alt landed, provenance unrecoverable".
			$expected_provenance = $this->expected_meta_after_core_transforms( '_acx_description_provenance', $provenance );
			update_post_meta( $media_id, '_acx_description_provenance', $provenance );
			$current_prov = get_post_meta( $media_id, '_acx_description_provenance', true );
			// Accept only a full-payload match. Partial key matches would forge
			// applied while history still lacks the expected provenance.
			$prov_ok = is_array( $current_prov ) && $expected_provenance === $current_prov;
			if ( ! $prov_ok ) {
				// Durable evidence this system started the write for this
				// run+draft. Inspect marker write the same way as provenance:
				// update_post_meta returns false on failure *and* on unchanged
				// value — re-read before claiming the marker. Without a usable
				// same-draft marker, auto-recovery is impossible so bucket
				// `failed` (not `partial`) — partial is presented as retryable.
				// [BR-102] [RLSE-05] [INT-11] [R21-BR-08]
				// draft_hash domain = stored form ($expected_stored_alt), not raw $draft [R22-BR-01].
				//
				// R23-BR-20: preserve the recovery originator on re-plant. When
				// this apply is completing a foreign-started write and provenance
				// fails, do not overwrite the marker owner with the applying run
				// — that made a second consecutive failure attribute the write to
				// the intermediate recoverer. Prefer recovered_from.origin (or an
				// existing foreign marker owner); plant chain so later recovery
				// still names the true originator.
				$expected_stored_alt_str = is_string( $expected_stored_alt )
					? $expected_stored_alt
					: (string) $expected_stored_alt;
				$marker_owner            = $run_id;
				// $recovered_from is always the array descriptor (empty or resolved).
				$marker_chain            = DescriptionHistoryService::normalize_recovery_chain(
					$recovered_from['chain'] ?? null
				);
				$recovery_origin         = $recovered_from['origin'] ?? null;
				if ( is_string( $recovery_origin ) && '' !== trim( $recovery_origin ) ) {
					$marker_owner = trim( $recovery_origin );
					$marker_chain = DescriptionHistoryService::append_recovery_origin( $marker_chain, $marker_owner );
				} else {
					$existing_marker = get_post_meta( $media_id, '_acx_description_provenance_pending', true );
					if ( DescriptionHistoryService::is_verified_pending_marker( $existing_marker )
						&& is_array( $existing_marker )
					) {
						$existing_owner = trim( (string) ( $existing_marker['run_id'] ?? '' ) );
						if ( '' !== $existing_owner && $existing_owner !== $run_id ) {
							// Preserve foreign originator across re-plant.
							$marker_owner = $existing_owner;
							if ( isset( $existing_marker['chain'] ) ) {
								foreach ( DescriptionHistoryService::normalize_recovery_chain( $existing_marker['chain'] ) as $entry ) {
									$marker_chain = DescriptionHistoryService::append_recovery_origin( $marker_chain, $entry );
								}
							}
							$marker_chain = DescriptionHistoryService::append_recovery_origin( $marker_chain, $marker_owner );
						}
					}
				}
				$marker = array(
					'run_id'     => $marker_owner,
					'draft_hash' => DescriptionHistoryService::hash_for_stored_alt( $expected_stored_alt_str ),
				);
				if ( array() !== $marker_chain ) {
					$marker['chain'] = $marker_chain;
				}
				// Return value is not authoritative (false = failure or no-op;
				// non-false may still persist a divergent value). Always verify
				// storage — partial requires a usable same-draft marker
				// [R20-BR-20] [R21-BR-08] (not strict identity with this plant).
				update_post_meta(
					$media_id,
					'_acx_description_provenance_pending',
					$marker
				);
				$current_marker = get_post_meta( $media_id, '_acx_description_provenance_pending', true );
				$marker_ok      = DescriptionHistoryService::is_usable_pending_marker_for_draft(
					$current_marker,
					$expected_stored_alt_str
				);
				if ( ! $marker_ok ) {
					// Alt remains written. failed = unrecoverable provenance gap,
					// not "nothing was written" [R21-BR-09].
					$buckets['failed'][] = $media_id;
					continue;
				}
				$buckets['partial'][] = $media_id;
				continue;
			}

			// Provenance verified — drop any pending recovery marker.
			// R21-BR-10: delete unchecked. A surviving marker is redundant:
			// history lists via the verified provenance array (not pure-gap),
			// and applied is still the correct bucket. Zombie cleared later.
			delete_post_meta( $media_id, '_acx_description_provenance_pending' );
			// [INT-09] decorative clear failed after verified alt → partial
			// (secondary durable write lag), not applied. See clear path above.
			if ( $decorative_clear_failed ) {
				$buckets['partial'][] = $media_id;
			} else {
				$buckets['applied'][] = $media_id;
			}
		}

		// Envelope from the centralised bucket surface — same six keys, same order.
		$body = array( 'run_id' => $run_id );
		foreach ( AltTextWriteStatus::BULK_APPLY_BUCKETS as $bucket_key ) {
			$body[ $bucket_key ] = $buckets[ $bucket_key ];
		}

		return new WP_REST_Response( $body, 200 );
	}

	/**
	 * Collapse apply-item rows by positive-integer media_id. Prefer the first row
	 * that carries a non-empty draft so a failed null-draft echo before a
	 * completed draft is not the only survivor (BR-106). When both rows have
	 * drafts, first-seen still wins (BR-92 bucket exclusivity). Callers must
	 * already have strict-validated media_id (BR-129).
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
			$media_id = $this->parse_strict_positive_int( $item['media_id'] ?? null ) ?? 0;
			if ( $media_id > 0 ) {
				if ( isset( $seen[ $media_id ] ) ) {
					$existing_index = $seen[ $media_id ];
					// $normalized only stores array items (non-arrays are skipped above).
					$existing       = $normalized[ $existing_index ];
					$existing_draft = is_string( $existing['alt_text_draft'] ?? null )
						? trim( $existing['alt_text_draft'] )
						: '';
					$new_draft      = is_string( $item['alt_text_draft'] ?? null )
						? trim( $item['alt_text_draft'] )
						: '';
					// Replace only when the kept row has no usable draft and the
					// later row does — never invent counts of dropped rows.
					if ( '' === $existing_draft && '' !== $new_draft ) {
						$normalized[ $existing_index ] = $item;
					}
					continue;
				}
				$seen[ $media_id ] = count( $normalized );
			}
			$normalized[] = $item;
		}

		return $normalized;
	}

	/**
	 * BR-129 / BR-134 / BR-143: persist the media_id set submitted for a run as a
	 * non-autoloaded option (membership is an authorization record, not a
	 * cache). Honors update_option's return: if the write fails, the caller
	 * must not report submit success. Absent on apply → fail closed.
	 *
	 * BR-143: retry the membership write once before giving up — the run is
	 * already accepted upstream and burning paid compute; a transient options
	 * failure should not strand it after a single attempt. Still fail loud on
	 * persistent failure (never invent a 202).
	 *
	 * Membership is not deleted on successful apply — a legitimate second
	 * apply (partial-recovery / complete history) still needs it. Bounded by
	 * {@see prune_run_media_ids_index()}.
	 *
	 * @param int[] $media_ids
	 * @return true|WP_Error
	 */
	private function store_run_media_ids( string $run_id, array $media_ids ): true|WP_Error {
		if ( '' === $run_id || array() === $media_ids ) {
			return true;
		}

		$created_at = time();
		$record     = array(
			'media_ids'  => array_values( $media_ids ),
			'created_at' => $created_at,
		);
		$option_key = $this->run_media_ids_option_key( $run_id );

		// Non-autoload: membership is only read on apply, not on every page load.
		// BR-143: one retry on real failure (not on the unchanged-value no-op).
		$written = update_option( $option_key, $record, false );
		if ( false === $written && ! $this->run_media_ids_record_matches( $option_key, $media_ids ) ) {
			// update_option returns false on failure *and* when the value is
			// unchanged. Accept an already-matching durable record (BR-147);
			// otherwise retry once before failing loud.
			$written = update_option( $option_key, $record, false );
			if ( false === $written && ! $this->run_media_ids_record_matches( $option_key, $media_ids ) ) {
				return new WP_Error(
					'describe_run_media_ids_store_failed',
					sprintf(
						'Describe run %s was submitted but its media_id set could not be stored; drafts cannot be applied.',
						$run_id
					),
					array(
						'status' => 500,
						'run_id' => $run_id,
					)
				);
			}
		}

		$this->remember_run_media_ids_index( $run_id, $created_at );

		return true;
	}

	/**
	 * True when the durable membership option already holds the same media_id
	 * set (order-insensitive reindex via array_values). Used to treat
	 * update_option's "value unchanged" false as success, not storage failure.
	 *
	 * Reads option storage; result can change between update_option attempts.
	 *
	 * @param int[] $media_ids
	 * @phpstan-impure
	 */
	private function run_media_ids_record_matches( string $option_key, array $media_ids ): bool {
		$current = get_option( $option_key, null );

		return is_array( $current )
			&& isset( $current['media_ids'] )
			&& is_array( $current['media_ids'] )
			&& array_values( $current['media_ids'] ) === array_values( $media_ids );
	}

	/**
	 * @return int[]|null Null when no local record exists (fail closed). No TTL
	 *                    gate — age pruning happens on write via the index.
	 */
	private function load_run_media_ids( string $run_id ): ?array {
		if ( '' === $run_id ) {
			return null;
		}

		$stored = get_option( $this->run_media_ids_option_key( $run_id ), null );
		if ( ! is_array( $stored ) ) {
			return null;
		}

		$raw_ids = $stored['media_ids'] ?? null;
		if ( ! is_array( $raw_ids ) || array() === $raw_ids ) {
			return null;
		}

		$media_ids = array();
		foreach ( $raw_ids as $raw ) {
			$parsed = $this->parse_strict_positive_int( $raw );
			if ( null !== $parsed ) {
				$media_ids[] = $parsed;
			}
		}

		return array() === $media_ids ? null : array_values( array_unique( $media_ids ) );
	}

	private function run_media_ids_option_key( string $run_id ): string {
		return self::RUN_MEDIA_IDS_OPTION_PREFIX . $run_id;
	}

	/**
	 * Maintain a bounded index of run_id => created_at. Prune by age (30d) and
	 * cap (200), deleting membership options for evicted runs (oldest first,
	 * subject to the BR-142 retention floor on cap eviction).
	 *
	 * BR-148: the index is the only thing that can ever delete a membership
	 * option. Check update_option's return and retry once. On persistent failure
	 * keep the membership record (never revoke authorization to tidy an index)
	 * but log so the condition is not swallowed.
	 */
	private function remember_run_media_ids_index( string $run_id, int $created_at ): void {
		$index = get_option( self::RUN_MEDIA_IDS_INDEX_OPTION, array() );
		if ( ! is_array( $index ) ) {
			$index = array();
		}

		$index[ $run_id ] = $created_at;
		$index             = $this->prune_run_media_ids_index( $index );

		$written = update_option( self::RUN_MEDIA_IDS_INDEX_OPTION, $index, false );
		if ( false !== $written ) {
			return;
		}
		// update_option returns false on failure *and* when the value is
		// unchanged — re-read before treating it as a real write failure.
		$current = get_option( self::RUN_MEDIA_IDS_INDEX_OPTION, null );
		if ( is_array( $current ) && $current === $index ) {
			return;
		}
		// BR-148: retry once.
		$written = update_option( self::RUN_MEDIA_IDS_INDEX_OPTION, $index, false );
		if ( false !== $written ) {
			return;
		}
		$current = get_option( self::RUN_MEDIA_IDS_INDEX_OPTION, null );
		if ( is_array( $current ) && $current === $index ) {
			return;
		}
		// Keep membership; do not delete the option just because the index
		// could not be updated. Surface the condition for ops.
		Telemetry::log_line(
			sprintf(
				'[acx] describe run media_ids index write failed after 2 attempts for run_id=%s; membership retained',
				$run_id
			)
		);
	}

	/**
	 * @param array<string,mixed> $index
	 * @return array<string,int>
	 */
	private function prune_run_media_ids_index( array $index ): array {
		$now     = time();
		$cleaned = array();

		foreach ( $index as $run_id => $created_at ) {
			if ( ! is_string( $run_id ) || '' === $run_id || ! is_numeric( $created_at ) ) {
				continue;
			}
			$created_at = (int) $created_at;
			if ( ( $now - $created_at ) > self::RUN_MEDIA_IDS_MAX_AGE_SECONDS ) {
				delete_option( $this->run_media_ids_option_key( $run_id ) );
				continue;
			}
			$cleaned[ $run_id ] = $created_at;
		}

		// BR-142: cap eviction only removes entries older than the retention
		// floor. If every entry is recent, let the index exceed the cap rather
		// than revoke a still-appliable run.
		if ( count( $cleaned ) > self::RUN_MEDIA_IDS_INDEX_MAX_ENTRIES ) {
			asort( $cleaned, SORT_NUMERIC );
			$excess  = count( $cleaned ) - self::RUN_MEDIA_IDS_INDEX_MAX_ENTRIES;
			$evicted = 0;
			foreach ( $cleaned as $run_id => $created_at ) {
				if ( $evicted >= $excess ) {
					break;
				}
				if ( ( $now - $created_at ) <= self::RUN_MEDIA_IDS_CAP_EVICTION_MIN_AGE_SECONDS ) {
					// Remaining entries are at least as recent (asort); stop.
					break;
				}
				delete_option( $this->run_media_ids_option_key( $run_id ) );
				unset( $cleaned[ $run_id ] );
				++$evicted;
			}
		}

		return $cleaned;
	}

	/**
	 * BR-129: accept only a positive int, or a pure digit string of a positive
	 * int. Rejects coercible junk such as "71junk" (which (int) would turn into 71).
	 */
	private function parse_strict_positive_int( mixed $value ): ?int {
		if ( is_int( $value ) ) {
			return $value > 0 ? $value : null;
		}
		if ( is_string( $value ) && '' !== $value && ctype_digit( $value ) ) {
			$as_int = (int) $value;

			return $as_int > 0 ? $as_int : null;
		}

		return null;
	}

	/**
	 * Whether stored provenance already attributes the currently stored alt.
	 *
	 * Writers stamp `alt_text_draft` with the exact draft string written
	 * (build_run_apply_provenance). That key is the raw sanitize_text_field
	 * draft, while stored alt is post wp_unslash+sanitize_meta — so comparison
	 * is in the **stored** domain: transform the provenance draft the same way
	 * core would and require equality with the stored alt. Direct string
	 * compare against stored alt would miss backslash-bearing drafts [BR-17].
	 *
	 * Returns false (recovery still allowed) when provenance is empty/non-array,
	 * lacks a usable alt_text_draft, or names a different draft (stale envelope
	 * superseded by a newer alt). True only when the envelope already describes
	 * this stored alt — non-clobber completion must not re-stamp run_id /
	 * applied_at [R23-BR-02]. Lives on the controller (not DescriptionHistoryService)
	 * because only this apply path gates non-clobber recovery and the transform
	 * helper is instance-scoped via ExpectsMetaAfterCoreTransforms.
	 *
	 * @param mixed  $provenance Raw `_acx_description_provenance` meta.
	 * @param string $stored_alt Currently stored alt (string branch only).
	 */
	private function provenance_already_describes_stored_alt( mixed $provenance, string $stored_alt ): bool {
		if ( ! is_array( $provenance ) ) {
			return false;
		}
		$draft_key = $provenance['alt_text_draft'] ?? null;
		if ( ! is_string( $draft_key ) || '' === trim( $draft_key ) ) {
			return false;
		}
		$expected_from_prov = $this->expected_meta_after_core_transforms( '_wp_attachment_image_alt', $draft_key );
		return is_string( $expected_from_prov ) && $expected_from_prov === $stored_alt;
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
	 * Always stamps `recovered_from` = `{ origin, kind, chain }` [R23-BR-20/21/22].
	 * Callers pass the canonical descriptor from
	 * {@see DescriptionHistoryService::resolve_recovery_descriptor()} or
	 * {@see DescriptionHistoryService::empty_recovered_from()} — never invent
	 * foreign model metadata [R23-BR-08] [rg-015]. A prior envelope's
	 * `recovered_from` on `$incoming` is merged into the resolver via the
	 * controller (chain passthrough); this builder always emits the resolved
	 * descriptor and never the deleted scalar `recovered_from_run_id`.
	 *
	 * @param mixed                    $incoming        Backend-supplied item provenance (may be null/scalar).
	 * @param string                   $run_id          Describe-run id stamped onto the envelope.
	 * @param string                   $draft           Exact alt draft string being written.
	 * @param array<string,mixed>|null $recovered_from  Always-present recovery descriptor (or null → empty).
	 *
	 * @return array<string,mixed>
	 */
	private function build_run_apply_provenance( mixed $incoming, string $run_id, string $draft, ?array $recovered_from = null ): array {
		$incoming   = is_array( $incoming ) ? $incoming : array();
		$provenance = array();
		// recovered_from is intentionally NOT copied from incoming here — the
		// resolved descriptor below is authoritative (controller already merged
		// any prior envelope chain into $recovered_from) [R23-BR-20].
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
		// Always emit the recovery descriptor [R23-BR-22]. Greenfield: no
		// recovered_from_run_id dual-write [R23-BR-20].
		$provenance['recovered_from'] = is_array( $recovered_from )
			? $recovered_from
			: DescriptionHistoryService::empty_recovered_from();

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
