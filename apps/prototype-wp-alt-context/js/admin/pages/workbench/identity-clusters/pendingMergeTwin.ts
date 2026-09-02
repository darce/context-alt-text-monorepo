import type { PendingMergeSuggestion } from '../../../api/recognition/types';
import { isMeaningfulMergeLabel } from './resolveMergeSurvivor';

export interface PendingMergeTwin {
  suggestionId: string;
  survivorLabel: string;
}

/**
 * Pending (pre-accept) twin for an unlabeled cluster: exactly one side of the
 * suggestion has a meaningful label (DATA-14 / `isMeaningfulMergeLabel`), and
 * `clusterId` is the unlabeled side. Both-labeled and neither-labeled pairs
 * yield no chip. Uses the same predicate as merge-survivor ranking.
 */
export const pendingMergeTwinForCluster = (
  clusterId: string | null,
  suggestions: readonly PendingMergeSuggestion[],
): PendingMergeTwin | null => {
  if (!clusterId) {
    return null;
  }

  for (const suggestion of suggestions) {
    if (suggestion.status && suggestion.status !== 'pending') {
      continue;
    }
    const aLabeled = isMeaningfulMergeLabel(suggestion.cluster_a_label);
    const bLabeled = isMeaningfulMergeLabel(suggestion.cluster_b_label);
    if (aLabeled === bLabeled) {
      continue;
    }
    const rawSurvivor = aLabeled ? suggestion.cluster_a_label : suggestion.cluster_b_label;
    const survivorLabel = rawSurvivor?.trim();
    const unlabeledId = aLabeled ? suggestion.cluster_b_id : suggestion.cluster_a_id;
    if (!survivorLabel || unlabeledId !== clusterId) {
      continue;
    }
    return { suggestionId: suggestion.id, survivorLabel };
  }

  return null;
};
