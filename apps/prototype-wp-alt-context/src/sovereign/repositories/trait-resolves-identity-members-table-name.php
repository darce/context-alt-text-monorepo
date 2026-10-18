<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function is_object;
use function is_string;

trait ResolvesIdentityMembersTableName {
	private function resolve_identity_members_table_name(): string {
		global $wpdb;

		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			return $wpdb->prefix . 'acx_identity_members';
		}

		return 'wp_acx_identity_members';
	}
}
