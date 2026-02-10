<?php

declare(strict_types=1);

namespace AltContext\Media;

/**
 * Placeholder for sovereign/local-table face metrics reads.
 */
class LocalProjectionFaceMetricsSource implements FaceMetricsSourceInterface {
	/**
	 * @return array<int,array<string,mixed>>
	 */
	public function get_identities_for_attachment( int $attachment_id ): array {
		return array();
	}
}
