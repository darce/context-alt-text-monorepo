<?php
/**
 * Standalone public guide document. No theme header/footer.
 *
 * @package AltContext
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

$acx_guide_canonical = home_url( '/guide/' );
$acx_guide_fallback  = \AltContext\PublicSite\PublicGuideRoute::fallback_copy();
$acx_guide_loading   = \AltContext\PublicSite\PublicGuideRoute::loading_copy();
$acx_guide_timeout   = \AltContext\PublicSite\PublicGuideRoute::LOAD_TIMEOUT_MS;
?><!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title><?php echo esc_html__( "Demo: names change a photo's meaning | AltContext", 'alt-context' ); ?></title>
	<meta name="description" content="<?php echo esc_attr( __( 'Try the AltContext demo. Write an image description (alt text) and choose who is named in each photo.', 'alt-context' ) ); ?>">
	<link rel="canonical" href="<?php echo esc_url( $acx_guide_canonical ); ?>">
	<?php // Keep the standalone guide's approved title when the theme adds its own title tag.
	remove_action( 'wp_head', '_wp_render_title_tag', 1 ); ?>
	<?php wp_head(); ?>
</head>
<body <?php body_class( 'acx-public-guide' ); ?>>
<main id="acx-public-guide" data-scope="recorded" data-example="bundled" data-acx-load-timeout="<?php echo esc_attr( (string) $acx_guide_timeout ); ?>">
	<p class="acx-public-guide__loading" aria-live="polite"><?php echo esc_html( $acx_guide_loading ); ?></p>
	<p class="acx-public-guide__fallback" role="alert" hidden><?php echo esc_html( $acx_guide_fallback ); ?></p>
	<noscript>
		<style>
			.acx-public-guide__loading { display: none !important; }
			.acx-public-guide__fallback[hidden] { display: block !important; }
		</style>
		<p><?php echo esc_html( $acx_guide_fallback ); ?></p>
	</noscript>
</main>
<?php wp_footer(); ?>
</body>
</html>
