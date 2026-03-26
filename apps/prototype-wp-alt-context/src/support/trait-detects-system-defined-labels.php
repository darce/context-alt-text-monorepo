<?php

declare(strict_types=1);

namespace AltContext\Support;

use function preg_match;

trait DetectsSystemDefinedLabels {
	protected function looks_like_system_defined_label( string $label ): bool {
		return 1 === preg_match( '/^cluster[-_][a-f0-9-]{8,}$/i', $label );
	}
}
