<?php

declare(strict_types=1);

namespace AltContext\Support;

use function is_string;
use function preg_match;
use function preg_replace;

trait DetectsSystemDefinedLabels {
	protected function is_reserved_label_shape( string $label ): bool {
		$normalized = preg_replace( '/^[\s\p{Z}\x{FEFF}]+|[\s\p{Z}\x{FEFF}]+$/u', '', $label );
		return 1 === preg_match( '/^cluster[-_]/i', is_string( $normalized ) ? $normalized : $label );
	}

	protected function looks_like_system_defined_label( string $label ): bool {
		return 1 === preg_match( '/^cluster[-_][a-f0-9-]{8,}$/i', $label );
	}

	/**
	 * SQL predicate matching is_reserved_label_shape (/^cluster[-_]/i).
	 * %% survives $wpdb->prepare; underscore is escaped so it is literal.
	 */
	protected function reserved_label_sql_predicate( string $column ): string {
		return '(' . $column . " LIKE 'cluster-%%' OR " . $column . " LIKE 'cluster\\_%%')";
	}

	/**
	 * Persons own human names (DATA-14). Auto/empty cluster labels may surface.
	 */
	protected function projected_cluster_label_sql( string $person_col = 'p.name', string $label_col = 'c.label' ): string {
		$reserved = $this->reserved_label_sql_predicate( $label_col );

		return "CASE WHEN {$person_col} IS NOT NULL AND {$person_col} <> '' THEN {$person_col} WHEN {$label_col} IS NULL OR {$label_col} = '' OR {$reserved} THEN {$label_col} ELSE NULL END";
	}
}
