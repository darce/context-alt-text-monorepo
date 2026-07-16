<?php
/**
 * E19-1 S7: headless one-image describe smoke.
 *
 * Resolves a single image attachment (the first by ID, or the `MEDIA_ID` arg),
 * dispatches it twice through `POST /acx/v1/recognition/describe`, and proves
 * the cache by natural repeat: the first call populates the cache, the second
 * must return `cached=true` with an identical `image_hash`. No `force`/bypass
 * field (deferred to Phase-1 stretch). Emits evidence JSON to stdout.
 *
 * Exit codes: 1 = setup/precondition failure, 2 = a describe call failed,
 * 3 = cache/stability assertion failed.
 */

declare(strict_types=1);

if ( ! defined( 'WP_CLI' ) || ! WP_CLI ) {
	fwrite( STDERR, "This script must be run via WP-CLI.\n" );
	exit( 1 );
}

$args               = is_array( $args ?? null ) ? $args : array();
$requested_media_id = isset( $args[0] ) ? (int) $args[0] : 0;

$admin_ids = get_users(
	array(
		'role'   => 'administrator',
		'number' => 1,
		'fields' => 'ids',
	)
);

if ( empty( $admin_ids ) ) {
	fwrite( STDERR, "No administrator user found for REST dispatch.\n" );
	exit( 1 );
}

wp_set_current_user( (int) $admin_ids[0] );

// RECOG-1: hosted `service` is the canonical default; the `acx_recognition_source`
// option tier is retired. `local` survives only as a dev-only hatch via the
// ACX_RECOGNITION_SOURCE constant / acx_recognition_source filter. This smoke runs
// against whatever source is effective (service by default, or local when the dev
// hatch is active) rather than hard-requiring local. Endpoint routing and auth are
// resolved by the plugin's recognition resolver during REST dispatch below.
$recognition_source = '';
if ( defined( 'ACX_RECOGNITION_SOURCE' ) && is_string( ACX_RECOGNITION_SOURCE ) ) {
	$recognition_source = trim( ACX_RECOGNITION_SOURCE );
}
if ( '' === $recognition_source ) {
	$recognition_source = trim( (string) apply_filters( 'acx_recognition_source', '' ) );
}
if ( '' === $recognition_source ) {
	$recognition_source = 'service';
}

if ( $requested_media_id > 0 ) {
	$media_id  = $requested_media_id;
	$mime_type = (string) get_post_mime_type( $media_id );
	if ( 'attachment' !== get_post_type( $media_id ) || 0 !== strpos( $mime_type, 'image/' ) ) {
		fwrite( STDERR, sprintf( "media_id=%d is not an image attachment.\n", $media_id ) );
		exit( 1 );
	}
} else {
	$found = get_posts(
		array(
			'post_type'      => 'attachment',
			'post_status'    => 'inherit',
			'post_mime_type' => 'image',
			'fields'         => 'ids',
			'posts_per_page' => 1,
			'orderby'        => 'ID',
			'order'          => 'ASC',
		)
	);
	if ( ! is_array( $found ) || count( $found ) < 1 ) {
		fwrite( STDERR, "No image attachments found to describe.\n" );
		exit( 1 );
	}
	$media_id = (int) $found[0];
}

/**
 * @return array<string,mixed>
 */
function acx_describe_once( int $media_id ): array {
	$request = new WP_REST_Request( 'POST', '/acx/v1/recognition/describe' );
	$request->set_body_params( array( 'media_id' => $media_id ) );
	$response = rest_do_request( $request );

	if ( is_wp_error( $response ) ) {
		return array(
			'ok'            => false,
			'error_code'    => $response->get_error_code(),
			'error_message' => $response->get_error_message(),
		);
	}

	$status = (int) $response->get_status();
	$data   = $response->get_data();

	return array(
		'ok'          => $status >= 200 && $status < 300 && is_array( $data ),
		'http_status' => $status,
		'data'        => is_array( $data ) ? $data : array(),
	);
}

$first  = acx_describe_once( $media_id );
$second = acx_describe_once( $media_id );

$first_data  = is_array( $first['data'] ?? null ) ? $first['data'] : array();
$second_data = is_array( $second['data'] ?? null ) ? $second['data'] : array();

$attachment_post = get_post( $media_id );
$attachment_path = get_attached_file( $media_id, true );

$payload = array(
	'site_url'           => get_site_url(),
	'recognition_source' => $recognition_source,
	'source_attachment'  => array(
		'media_id'  => $media_id,
		'title'     => is_object( $attachment_post ) ? (string) ( $attachment_post->post_title ?? '' ) : '',
		'filename'  => is_string( $attachment_path ) ? basename( $attachment_path ) : '',
		'mime_type' => (string) get_post_mime_type( $media_id ),
	),
	'first_http_status'  => $first['http_status'] ?? null,
	'second_http_status' => $second['http_status'] ?? null,
	'first_cached'       => $first_data['cached'] ?? null,
	'second_cached'      => $second_data['cached'] ?? null,
	'image_hash'         => $first_data['image_hash'] ?? null,
	'context_hash'       => $first_data['context_hash'] ?? null,
	'adapter'            => $first_data['adapter'] ?? null,
	'model_id'           => $first_data['model_id'] ?? null,
	'alt_text_draft'     => $first_data['alt_text_draft'] ?? null,
	'duration_ms_first'  => $first_data['duration_ms'] ?? null,
	'duration_ms_second' => $second_data['duration_ms'] ?? null,
);

if ( ! ( $first['ok'] ?? false ) ) {
	$payload['first_error'] = array(
		'error_code'    => $first['error_code'] ?? null,
		'error_message' => $first['error_message'] ?? null,
	);
}
if ( ! ( $second['ok'] ?? false ) ) {
	$payload['second_error'] = array(
		'error_code'    => $second['error_code'] ?? null,
		'error_message' => $second['error_message'] ?? null,
	);
}

echo wp_json_encode( $payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES ) . PHP_EOL;

if ( ! ( $first['ok'] ?? false ) || ! ( $second['ok'] ?? false ) ) {
	fwrite( STDERR, "A describe call failed; see evidence JSON above.\n" );
	exit( 2 );
}

if ( false !== ( $first_data['cached'] ?? null ) || true !== ( $second_data['cached'] ?? null ) ) {
	fwrite( STDERR, "Describe cache proof failed (expected first_cached=false and second_cached=true).\n" );
	exit( 3 );
}

$first_hash  = (string) ( $first_data['image_hash'] ?? '' );
$second_hash = (string) ( $second_data['image_hash'] ?? '' );
if ( '' === $first_hash || $first_hash !== $second_hash ) {
	fwrite( STDERR, "image_hash missing or not stable across the two calls.\n" );
	exit( 3 );
}
