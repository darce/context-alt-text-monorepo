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
$acx_guide_home      = home_url( '/' );
$acx_guide_fallback  = \AltContext\PublicSite\PublicGuideRoute::fallback_copy();
?><!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	<title><?php echo esc_html__( 'Guide', 'alt-context' ); ?></title>
	<link rel="canonical" href="<?php echo esc_url( $acx_guide_canonical ); ?>">
	<?php wp_head(); ?>
</head>
<body <?php body_class( 'acx-public-guide' ); ?>>
<main id="acx-public-guide" data-scope="recorded" data-example="bundled" data-home-url="<?php echo esc_url( $acx_guide_home ); ?>">
	<p class="acx-public-guide__fallback" role="alert"><?php echo esc_html( $acx_guide_fallback ); ?></p>
	<noscript>
		<p><?php echo esc_html( $acx_guide_fallback ); ?></p>
	</noscript>
</main>
<?php wp_footer(); ?>
</body>
</html>
