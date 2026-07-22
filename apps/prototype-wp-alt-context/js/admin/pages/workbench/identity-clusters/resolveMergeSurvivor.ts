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
import { AUTO_LABEL_PREFIX } from './suggestionProjection';

export interface MergeSurvivorResolution {
  survivorId: string;
  retiredId: string;
}

/**
 * Meaningful label = non-empty ∧ not auto `cluster-*`. BR-69: mirror backend
 * `_is_meaningful_label` byte-for-byte — it does NOT trim, so a whitespace-padded
 * label ranks as meaningful on the server. The trimming `isHumanLabeledTarget`
 * would disagree on padded labels and mis-rank the survivor guess.
 */
export const isMeaningfulMergeLabel = (label: string | null | undefined): boolean => {
  if (!label) {
    return false;
  }
  return !label.startsWith(AUTO_LABEL_PREFIX);
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
 * Authoritative post-accept ids when both are present and distinct.
 * Returns null when the response lacks topology (pending list / older backend).
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
