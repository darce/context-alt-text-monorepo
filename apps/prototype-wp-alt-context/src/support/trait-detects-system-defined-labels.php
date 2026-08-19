<?php

declare(strict_types=1);

namespace AltContext\Support;

use function is_string;
use function preg_match;
use function preg_replace;

trait DetectsSystemDefinedLabels {
	protected const CLUSTER_LABEL_STATE_PERSON    = 'person';
	protected const CLUSTER_LABEL_STATE_UNLABELED = 'unlabeled';
	protected const CLUSTER_LABEL_STATE_UNBOUND   = 'unbound';

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
		$lower = 'LOWER(' . $column . ')';

		return '(' . $lower . " LIKE 'cluster-%%' OR " . $lower . " LIKE 'cluster\\_%%')";
	}

	/**
	 * Persons own human names (DATA-14). Auto/empty cluster labels may surface.
	 */
	protected function projected_cluster_label_sql( string $person_col = 'p.name', string $label_col = 'c.label' ): string {
		$reserved = $this->reserved_label_sql_predicate( $label_col );

		return "CASE WHEN {$person_col} IS NOT NULL AND {$person_col} <> '' THEN {$person_col} WHEN {$label_col} IS NULL OR {$label_col} = '' OR {$reserved} THEN {$label_col} ELSE NULL END";
	}

	/**
	 * Named label authority for the FE: person | unlabeled | unbound.
	 * Mirrors projected_cluster_label_sql so a null label is not inferred.
	 */
	protected function projected_cluster_label_state_sql( string $person_col = 'p.name', string $label_col = 'c.label' ): string {
		$reserved = $this->reserved_label_sql_predicate( $label_col );
		$person   = self::CLUSTER_LABEL_STATE_PERSON;
		$unlabeled = self::CLUSTER_LABEL_STATE_UNLABELED;
		$unbound  = self::CLUSTER_LABEL_STATE_UNBOUND;

		return "CASE WHEN {$person_col} IS NOT NULL AND {$person_col} <> '' THEN '{$person}' WHEN {$label_col} IS NULL OR {$label_col} = '' OR {$reserved} THEN '{$unlabeled}' ELSE '{$unbound}' END";
	}

	protected function projected_cluster_label_select_sql( string $person_col = 'p.name', string $label_col = 'c.label' ): string {
		return $this->projected_cluster_label_sql( $person_col, $label_col ) . ' AS cluster_label, '
			. $this->projected_cluster_label_state_sql( $person_col, $label_col ) . ' AS label_state';
	}

	protected function resolve_cluster_label_state( ?string $person_name, ?string $cluster_label ): string {
		if ( is_string( $person_name ) && '' !== $person_name ) {
			return self::CLUSTER_LABEL_STATE_PERSON;
		}

		if ( null === $cluster_label || '' === $cluster_label || $this->is_reserved_label_shape( $cluster_label ) ) {
			return self::CLUSTER_LABEL_STATE_UNLABELED;
		}

		return self::CLUSTER_LABEL_STATE_UNBOUND;
	}
}
