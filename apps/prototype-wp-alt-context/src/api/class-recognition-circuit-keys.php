<?php

declare(strict_types=1);

namespace AltContext\Api;

use function md5;
use function strtolower;
use function trim;

final class RecognitionCircuitKeys {
	public static function for_base_url( string $base_url ): string {
		return 'acx_recognition_circuit_' . md5( strtolower( trim( $base_url ) ) );
	}

	public static function failure_key_for_base_url( string $base_url ): string {
		return self::for_base_url( $base_url ) . '_failures';
	}
}
