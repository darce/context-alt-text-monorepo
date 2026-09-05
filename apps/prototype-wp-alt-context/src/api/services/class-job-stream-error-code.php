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
enum JobStreamErrorCode: string {
	case PROXY_ERROR          = 'proxy_error';
	case JOB_NOT_FOUND        = 'job_not_found';
	case UNEXPECTED_RESPONSE  = 'unexpected_response';
	case INVALID_JOB_RESPONSE = 'invalid_job_response';
}
