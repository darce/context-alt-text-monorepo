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
}
