/**
 * Client-side reduction for the batched inline-suggestion query.
 *
 * Replicates per-identity route semantics (labeled-only, top-1 by similarity)
 * over the shared GET /recognition/suggestions pages.
 */

import { fetchPendingSuggestions } from '../../../api/recognition';
import type { ClusterSuggestion, PendingSuggestion } from '../../../api/recognition';

/** Service max page size; requests per batch = ceil(P/500). */
export const INLINE_SUGGESTION_BATCH_LIMIT = 500;

/** Backstop against unbounded paging on a pathological pending backlog. */
export const INLINE_SUGGESTION_MAX_PAGES = 4;

/**
 * The batched call carries up to 500 rows — the 2s default abort built for
 * small per-identity reads is too tight for a single shared request.
 */
export const INLINE_SUGGESTION_BATCH_TIMEOUT_MS = 10_000;

/**
 * Top match for the inline prompt. Narrower than ClusterSuggestion: the list
 * payload's identity count may be null and the prompt never reads it, so it is
 * omitted rather than fabricated (rg-015).
 */
export type InlineTopMatch = Omit<ClusterSuggestion, 'identity_count'>;

export type InlineTopMatchByIdentity = ReadonlyMap<string, InlineTopMatch>;

/**
 * Fetch every pending-suggestion page (ceil(P/500) requests, bounded by
 * INLINE_SUGGESTION_MAX_PAGES so a runaway backlog cannot loop forever).
 */
export const fetchAllPendingSuggestionRows = async (): Promise<PendingSuggestion[]> => {
  const rows: PendingSuggestion[] = [];
  for (let page = 0; page < INLINE_SUGGESTION_MAX_PAGES; page += 1) {
    const response = await fetchPendingSuggestions(
      INLINE_SUGGESTION_BATCH_LIMIT,
      page * INLINE_SUGGESTION_BATCH_LIMIT,
      INLINE_SUGGESTION_BATCH_TIMEOUT_MS,
    );
    rows.push(...response.suggestions);
    if (response.suggestions.length < INLINE_SUGGESTION_BATCH_LIMIT) {
      break;
    }
  }
  return rows;
};

/**
 * Group pending suggestion rows by identity_id, drop unlabeled clusters,
 * and keep the highest-similarity match per identity.
 */
export const reduceInlineSuggestionsByIdentity = (
  suggestions: readonly PendingSuggestion[],
): InlineTopMatchByIdentity => {
  const best = new Map<string, InlineTopMatch>();

  for (const row of suggestions) {
    const label = row.cluster_label?.trim();
    if (!label) {
      continue;
    }

    const similarity = row.representative_similarity;
    const existing = best.get(row.identity_id);
    if (existing !== undefined && existing.similarity >= similarity) {
      continue;
    }

    best.set(row.identity_id, {
      suggestion_id: row.id,
      cluster_id: row.suggested_cluster_id,
      label,
      similarity,
    });
  }

  return best;
};
