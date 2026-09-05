<?php

declare(strict_types=1);

namespace AltContext\Api\Services;

/**
 * Stable machine vocabulary for job-progress SSE error frames.
 *
 * Messages remain diagnostic and localizable; consumers make lifecycle
 * decisions from these values. Centralizing the vocabulary follows sr-007
 * (docs/workbay/constitution.md:24), while emitting an explicit failure result
 * avoids the silent-failure trap in RLSE-05
 * (heuristics-canon-research/lexicons/engineering.md:696).
 */
final class JobStreamErrorCode {
	// Keep the centralized wire vocabulary compatible with the advertised PHP
	// 8.0 minimum; backed enums require PHP 8.1.
	public const PROXY_ERROR          = 'proxy_error';
	public const JOB_NOT_FOUND        = 'job_not_found';
	public const UNEXPECTED_RESPONSE  = 'unexpected_response';
	public const INVALID_JOB_RESPONSE = 'invalid_job_response';

	private function __construct() {}

	/** @return list<string> */
	public static function cases(): array {
		return array_values( ( new \ReflectionClass( self::class ) )->getConstants() );
	}
}
