/**
 * Best-effort survivor selection for accepted merge suggestions.
 *
 * Backend `_select_merge_target` ranks clusters by
 * `(user_confirmed, meaningful_label, identity_count, id)` — higher wins.
 * `PendingMergeSuggestion` does NOT carry `user_confirmed`, so this client
 * replica ranks only `(meaningfulLabel(label), identity_count ?? 0, id)`.
 *
 * That makes the result a **guess**. Callers (useLiveReviewTarget) must
 * re-validate the guessed survivor via a live existence query and fall
 * through to close if the guess 404s (self-heal).
 */

import type { PendingMergeSuggestion } from '../../../api/recognition/types';
import { isHumanLabeledTarget } from './suggestionProjection';

export interface MergeSurvivorResolution {
  survivorId: string;
  retiredId: string;
}

/** Meaningful label = non-empty trimmed ∧ not auto `cluster-*` (matches backend `_is_meaningful_label`). */
export const isMeaningfulMergeLabel = (label: string | null | undefined): boolean =>
  isHumanLabeledTarget(label);

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

/**
 * Pick survivor/retired from a merge-suggestion accept response.
 * Best-effort only — see file header.
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
