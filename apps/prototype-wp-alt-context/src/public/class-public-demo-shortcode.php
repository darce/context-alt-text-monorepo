<?php

declare(strict_types=1);

namespace AltContext\PublicSite;

use function absint;
use function add_shortcode;
use function array_filter;
use function array_map;
use function array_unique;
use function array_values;
use function esc_attr;
use function esc_html;
use function esc_url;
use function get_option;
use function get_the_title;
use function is_array;
use function rest_url;
use function wp_create_nonce;
use function wp_enqueue_script;
use function wp_enqueue_style;
use function wp_get_attachment_image_url;
use function wp_script_add_data;

/** Registers and renders the [acx_demo_describe] public demo. */
final class PublicDemoShortcode {
	private const SCRIPT_HANDLE = 'acx-public-demo-describe';

	public function init(): void {
		add_shortcode( 'acx_demo_describe', array( $this, 'render' ) );
	}

	/** @param array<string,mixed> $attributes */
	public function render( array $attributes = array() ): string {
		unset( $attributes );
		if ( ! $this->is_enabled() ) {
			return '<div class="acx-demo" data-state="limited"><p class="acx-demo__status" role="status"><span aria-hidden="true">&#9888;</span> The image description demo is not available right now.</p></div>';
		}

		$choices = $this->choices();
		if ( array() === $choices ) {
			return '<div class="acx-demo" data-state="error"><p class="acx-demo__status" role="alert"><span aria-hidden="true">&#9888;</span> No demo images are available right now.</p></div>';
		}

		wp_enqueue_script(
			self::SCRIPT_HANDLE,
			esc_url( ACX_PLUGIN_URL . 'js/public/demo-describe.js' ),
			array(),
			ACX_VERSION,
			true
		);
		wp_script_add_data( self::SCRIPT_HANDLE, 'type', 'module' );
		wp_enqueue_style(
			self::SCRIPT_HANDLE,
			esc_url( ACX_PLUGIN_URL . 'js/public/demo-describe.css' ),
			array(),
			ACX_VERSION
		);

		static $instance = 0;
		++$instance;
		$group_name = 'acx-demo-media-' . $instance;
		$cards = '';
		foreach ( $choices as $choice ) {
			$input_id = $group_name . '-' . $choice['id'];
			$cards .= '<label class="acx-demo__choice" for="' . esc_attr( $input_id ) . '">';
			$cards .= '<input id="' . esc_attr( $input_id ) . '" type="radio" name="' . esc_attr( $group_name ) . '" value="' . esc_attr( (string) $choice['id'] ) . '" required>';
			$cards .= '<img src="' . esc_url( $choice['url'] ) . '" alt="">';
			$cards .= '<span>' . esc_html( $choice['title'] ) . '</span>';
			$cards .= '</label>';
		}

		$preview  = '<aside class="acx-demo__preview" data-acx-demo-preview>';
		$preview .= '<p>' . esc_html( 'Illustrative example — not a live result' ) . '</p>';
		$preview .= '<p>' . esc_html( 'Alex stands beside a bicycle outside a cafe.' ) . '</p>';
		$preview .= '<p>' . esc_html( 'This example is not a description of your selected image. Your live result may differ.' ) . '</p>';
		$preview .= '</aside>';

		return '<section class="acx-demo" data-acx-demo data-state="idle" data-submit-url="'
			. esc_attr( rest_url( 'acx/v1/public/demo/describe' ) )
			. '" data-nonce="' . esc_attr( wp_create_nonce( 'wp_rest' ) ) . '">'
			. $preview
			. '<form class="acx-demo__form"><fieldset><legend>Choose an image to describe</legend><div class="acx-demo__choices">'
			. $cards
			. '</div></fieldset><button type="submit" class="acx-demo__submit">Describe selected image</button></form>'
			. '<p class="acx-demo__status" data-acx-demo-status role="status" aria-live="polite"><span data-acx-demo-icon aria-hidden="true">&#9679;</span> <span data-acx-demo-message>Select an image, then choose Describe.</span></p>'
			. '<div class="acx-demo__result" data-acx-demo-result tabindex="-1" hidden></div>'
			. '</section>';
	}

	private function is_enabled(): bool {
		$value = get_option( 'acx_public_demo_enabled', false );
		return true === $value || 1 === $value || '1' === $value;
	}

	/** @return list<array{id:int,url:string,title:string}> */
	private function choices(): array {
		$configured = get_option( 'acx_public_demo_media_ids', array() );
		if ( ! is_array( $configured ) ) {
			return array();
		}

		$ids     = array_values( array_unique( array_filter( array_map( 'absint', $configured ) ) ) );
		$choices = array();
		foreach ( $ids as $id ) {
			$url = wp_get_attachment_image_url( $id, 'medium_large' );
			if ( false === $url ) {
				continue;
			}
			$title     = (string) get_the_title( $id );
			$choices[] = array(
				'id'    => $id,
				'url'   => $url,
				'title' => '' !== $title ? $title : 'Demo image ' . $id,
			);
		}

		return $choices;
	}
}
