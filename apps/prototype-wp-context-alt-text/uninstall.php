<?php

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
    wp_die( sprintf(
        __( '%s should only be called when uninstalling the plugin.', 'cat'), __FILE__
    ));
    exit;
}

$role = get_role( 'administrator' );
if ( ! empty( $role ) ) {
    $role->remove_cap( 'cat_manage_settings' );
}