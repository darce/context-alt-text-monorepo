<?php

declare(strict_types=1);

namespace AltContext\Support;

use function preg_match;
use function trim;

trait DetectsSystemDefinedLabels {
	protected function is_reserved_label_shape( string $label ): bool {
		return 1 === preg_match( '/^cluster[-_]/i', trim( $label ) );
	}

	protected function looks_like_system_defined_label( string $label ): bool {
		return 1 === preg_match( '/^cluster[-_][a-f0-9-]{8,}$/i', $label );
	}
}
