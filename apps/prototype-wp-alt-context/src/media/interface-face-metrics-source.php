<?php

declare(strict_types=1);

namespace AltContext\Media;

interface FaceMetricsSourceInterface {
	/**
	 * Return identities for a single attachment.
	 *
	 * @return array<int,array<string,mixed>>
	 */
	public function get_identities_for_attachment( int $attachment_id ): array;
}
