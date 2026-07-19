<?php

declare(strict_types=1);

namespace AltContext\Tests\Stubs;

use AltContext\Sovereign\Sync\SyncPullJobInterface;
use AltContext\Sovereign\Sync\SyncPullResult;

/**
 * Recording SyncPullJobInterface spy for convergence/heal-path assertions
 * (E15-37 slices 1-2). Configure failure/throw behavior via public fields.
 */
final class SpySyncPullJob implements SyncPullJobInterface {
	/** @var list<string> */
	public array $performCalls = array();

	/** @var list<string> */
	public array $bypassCalls = array();

	public bool $succeed = true;

	public ?SyncPullResult $performResult = null;

	public ?\Throwable $performThrows = null;

	/** @var ?callable(string):void */
	public $onPerform = null;

	/** @var ?callable(string):void */
	public $onBypass = null;

	public function perform( string $tenant_id ): SyncPullResult {
		$this->performCalls[] = $tenant_id;
		if ( null !== $this->performThrows ) {
			throw $this->performThrows;
		}
		if ( null !== $this->onPerform ) {
			( $this->onPerform )( $tenant_id );
		}

		return $this->performResult ?? SyncPullResult::ok();
	}

	public function perform_bypass_cooldown( string $tenant_id ): SyncPullResult {
		$this->bypassCalls[] = $tenant_id;
		if ( null !== $this->onBypass ) {
			( $this->onBypass )( $tenant_id );
		}

		return $this->succeed ? SyncPullResult::ok() : SyncPullResult::failed();
	}

	public function perform_projection_payload( string $tenant_id, array $payload ): SyncPullResult {
		return SyncPullResult::ok();
	}
}
