<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

final class OutboxStatus {
	public const PENDING = 'pending';
	public const IN_FLIGHT = 'in_flight';
	public const FAILED = 'failed';
	public const ACKNOWLEDGED = 'acknowledged';
	public const CONFLICT = 'conflict';
	public const DISCARDED = 'discarded';
}
