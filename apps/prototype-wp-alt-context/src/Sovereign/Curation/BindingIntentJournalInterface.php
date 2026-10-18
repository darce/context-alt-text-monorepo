<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Curation;

/** Durable authority, distinct from disposable projection repositories. */
interface BindingIntentJournalInterface {
	public function inspect( string $tenant_id ): array;

	/** Guard and commit participating local writes in the journal's transaction. */
	public function apply( string $tenant_id, array $command, callable $participate ): array;

	/** Commit multiple person transitions and writer effects together or none. */
	public function apply_batch( string $tenant_id, string $request_id, array $commands, callable $participate ): array;
}
