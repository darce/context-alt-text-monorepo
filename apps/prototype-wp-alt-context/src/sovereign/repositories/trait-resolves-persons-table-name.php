<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Repositories;

use function is_object;
use function is_string;

trait ResolvesPersonsTableName {
	private function resolve_persons_table_name(): string {
		global $wpdb;

		if ( isset( $wpdb ) && is_object( $wpdb ) && isset( $wpdb->prefix ) && is_string( $wpdb->prefix ) ) {
			return $wpdb->prefix . 'acx_persons';
		}

		return 'wp_acx_persons';
	}
}
