<?php

declare(strict_types=1);

namespace AltContext\Admin;

use function add_filter;
use function current_user_can;
use function esc_attr;
use function get_post_mime_type;
use function is_object;
use function is_string;
use function str_starts_with;

/**
 * Registers the attachment-edit face-overlay mount surface on post.php.
 *
 * Emits an inert container only; React owns first paint after the attachment-edit
 * bundle removes the `hidden` attribute (later slices).
 */
class AttachmentFields {
	public function init(): void {
		add_filter( 'attachment_fields_to_edit', array( $this, 'register_fields' ), 10, 2 );
	}

	/**
	 * @param array<string,array<string,mixed>> $form_fields
	 * @param object|\WP_Post                   $post
	 * @return array<string,array<string,mixed>>
	 */
	public function register_fields( array $form_fields, $post ): array {
		if ( ! current_user_can( 'manage_options' ) ) {
			return $form_fields;
		}

		$attachment_id = is_object( $post ) && isset( $post->ID ) ? (int) $post->ID : 0;
		if ( $attachment_id <= 0 ) {
			return $form_fields;
		}

		$mime = get_post_mime_type( $attachment_id );
		if ( ! is_string( $mime ) || ! str_starts_with( $mime, 'image/' ) ) {
			return $form_fields;
		}

		$form_fields['acx_attachment_faces'] = array(
			'label'         => '',
			'input'         => 'html',
			'html'          => sprintf(
				'<div id="acx-attachment-faces" data-attachment-id="%s" hidden></div>',
				esc_attr( (string) $attachment_id )
			),
			'show_in_modal' => false,
		);

		return $form_fields;
	}
}
