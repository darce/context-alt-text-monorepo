/**
 * Survivor selection for accepted merge suggestions.
 *
 * Prefer authoritative `source_cluster_id` (retired) / `target_cluster_id`
 * (survivor) stamped by the accept-merge response after `_select_merge_target`.
 * Fall back to a client rank replica only when those ids are absent (older
 * backends / list shapes). The fallback cannot see `user_confirmed`, so it
 * ranks only `(meaningfulLabel, identity_count, id)` — a **guess** that must
 * self-heal via existence probes when wrong.
 */

import type { PendingMergeSuggestion } from '../../../api/recognition/types';

export interface MergeSurvivorResolution {
  survivorId: string;
  retiredId: string;
}

/**
 * Meaningful label = non-empty after trim ∧ not a reserved machine shape.
 * DATA-14 / HARM-F5: mirror backend `is_reserved_label_shape` — trim, lowercase,
 * and treat both `cluster-` and `cluster_` prefixes as reserved. Do not use a
 * second inline prefix check at call sites (twin chip included).
 */
export const isMeaningfulMergeLabel = (label: string | null | undefined): boolean => {
  if (label == null) {
    return false;
  }
  const trimmed = label.trim();
  if (!trimmed) {
    return false;
  }
  const normalized = trimmed.toLowerCase();
  return !normalized.startsWith('cluster-') && !normalized.startsWith('cluster_');
};

type RankTuple = readonly [number, number, string];

const rankSide = (label: string | null | undefined, identityCount: number | null | undefined, id: string): RankTuple => [
  isMeaningfulMergeLabel(label) ? 1 : 0,
  identityCount ?? 0,
  id,
];

const compareRank = (a: RankTuple, b: RankTuple): number => {
  if (a[0] !== b[0]) {
    return a[0] - b[0];
  }
  if (a[1] !== b[1]) {
    return a[1] - b[1];
  }
  // Lexicographic id — mirrors Python tuple comparison on the id string.
  if (a[2] < b[2]) {
    return -1;
  }
  if (a[2] > b[2]) {
    return 1;
  }
  return 0;
};

const isNonEmptyClusterId = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0;

/**
 * Authoritative post-accept ids when both are present, distinct, and belong to
 * the suggestion's {cluster_a_id, cluster_b_id} pair (E215-BR-04). Mismatched
 * or foreign ids fall through to client-rank fallback.
 * Returns null when the response lacks trustworthy topology.
 */
export const authoritativeMergeSurvivor = (
  suggestion: PendingMergeSuggestion,
): MergeSurvivorResolution | null => {
  const retiredId = suggestion.source_cluster_id;
  const survivorId = suggestion.target_cluster_id;
  if (!isNonEmptyClusterId(retiredId) || !isNonEmptyClusterId(survivorId)) {
    return null;
  }
  if (retiredId === survivorId) {
    return null;
  }
  const pair = new Set([suggestion.cluster_a_id, suggestion.cluster_b_id]);
  if (!pair.has(retiredId) || !pair.has(survivorId)) {
    return null;
  }
  return { survivorId, retiredId };
};

/**
 * Best-effort rank replica for older backends that omit source/target ids.
 * Prefer {@link resolveMergeSurvivorFromResponse} on accept paths.
 */
export const resolveMergeSurvivor = (suggestion: PendingMergeSuggestion): MergeSurvivorResolution => {
  const aId = suggestion.cluster_a_id;
  const bId = suggestion.cluster_b_id;
  const aRank = rankSide(suggestion.cluster_a_label, suggestion.cluster_a_identity_count, aId);
  const bRank = rankSide(suggestion.cluster_b_label, suggestion.cluster_b_identity_count, bId);
  // Backend uses `>=` so ties (including id-equal — impossible for distinct clusters) prefer A.
  if (compareRank(aRank, bRank) >= 0) {
    return { survivorId: aId, retiredId: bId };
  }
  return { survivorId: bId, retiredId: aId };
};

/**
 * Accept-path survivor resolution: response ids first, client-rank fallback.
 */
export const resolveMergeSurvivorFromResponse = (
  suggestion: PendingMergeSuggestion,
): MergeSurvivorResolution => authoritativeMergeSurvivor(suggestion) ?? resolveMergeSurvivor(suggestion);
