<?php

declare(strict_types=1);

namespace AltContext\Sovereign\Curation;

/** Durable tenant fence shared by ALL binding, membership and snapshot writers. */
interface BindingJournalStore {
	/**
	 * Run once under an exclusive tenant fence and a database transaction.
	 * The callback receives the persisted state by reference. Commit it together
	 * with participating writer effects, or roll all of them back on any failure.
	 * Implementations must reject nesting and never retry a callback implicitly.
	 *
	 * @return mixed
	 */
	public function transaction( string $tenant_id, callable $operation );
}
