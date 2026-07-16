/**
 * Client-side reduction for the batched inline-suggestion query.
 *
 * Replicates per-identity route semantics (labeled-only, top-1 by similarity)
 * over the shared GET /recognition/suggestions page (limit=500).
 */

import type { ClusterSuggestion, PendingSuggestion } from '../../../api/recognition';

/** Service max page size — one request covers practical unlabeled-card counts. */
export const INLINE_SUGGESTION_BATCH_LIMIT = 500;

export type InlineTopMatchByIdentity = ReadonlyMap<string, ClusterSuggestion>;

/**
 * Group pending suggestion rows by identity_id, drop unlabeled clusters,
 * and keep the highest-similarity match per identity.
 */
export const reduceInlineSuggestionsByIdentity = (
  suggestions: readonly PendingSuggestion[],
): InlineTopMatchByIdentity => {
  const best = new Map<string, ClusterSuggestion>();

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
      identity_count: row.cluster_identity_count ?? 0,
    });
  }

  return best;
};
