<?php

declare(strict_types=1);

/**
 * @param array<int,mixed> $args
 * @return array{limit:int,batch_size:int,timeout_seconds:int,poll_interval_ms:int}
 */
function acx_parse_batch_run_smoke_args(array $args): array
{
	if ($args === []) {
		return [
			'limit' => 100,
			'batch_size' => 5,
			'timeout_seconds' => 240,
			'poll_interval_ms' => 1000,
		];
	}

	if (count($args) !== 4) {
		throw new RuntimeException('Expected either 0 or 4 smoke arguments.');
	}

	$spec = [
		'limit' => [0, 1],
		'batch_size' => [1, 1],
		'timeout_seconds' => [2, 1],
		'poll_interval_ms' => [3, 100],
	];
	$parsed = [];

	foreach ($spec as $name => [$index, $minimum]) {
		$value = $args[$index] ?? null;
		$normalized = is_scalar($value) ? trim((string) $value) : '';

		if ($normalized === '--') {
			throw new RuntimeException('Smoke arguments must not include the WP-CLI separator `--`.');
		}

		if ($normalized === '' || preg_match('/^\d+$/', $normalized) !== 1) {
			throw new RuntimeException(sprintf('Smoke argument `%s` must be an integer.', $name));
		}

		$parsed[$name] = (int) $normalized;

		if ($parsed[$name] < $minimum) {
			throw new RuntimeException(sprintf('Smoke argument `%s` must be at least %d.', $name, $minimum));
		}
	}

	return $parsed;
}