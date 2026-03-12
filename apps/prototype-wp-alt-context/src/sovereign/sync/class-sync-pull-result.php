<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Sync;

use InvalidArgumentException;

use function in_array;

final class SyncPullResult {
	public const OK = 'ok';
	public const FAILED = 'failed';
	public const UNREACHABLE = 'unreachable';
	public const SKIPPED = 'skipped';

	private string $status;

	private function __construct( string $status ) {
		if ( ! in_array( $status, self::allowed_statuses(), true ) ) {
			throw new InvalidArgumentException( 'Invalid sync pull result status.' );
		}

		$this->status = $status;
	}

	public static function ok(): self {
		return new self( self::OK );
	}

	public static function failed(): self {
		return new self( self::FAILED );
	}

	public static function unreachable(): self {
		return new self( self::UNREACHABLE );
	}

	public static function skipped(): self {
		return new self( self::SKIPPED );
	}

	public function status(): string {
		return $this->status;
	}

	public function is_success(): bool {
		return self::OK === $this->status;
	}

	/**
	 * @return string[]
	 */
	public static function allowed_statuses(): array {
		return array(
			self::OK,
			self::FAILED,
			self::UNREACHABLE,
			self::SKIPPED,
		);
	}
}
