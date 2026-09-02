import type { PendingMergeSuggestion } from '../../../api/recognition/types';
import { isMeaningfulMergeLabel } from './resolveMergeSurvivor';

export interface PendingMergeTwin {
  suggestionId: string;
  survivorClusterId: string;
  survivorLabel: string;
}

export interface MergeSurvivorPick {
  survivorClusterId: string;
  unlabeledId: string;
  survivorLabel: string;
}

const trimLabel = (value: string | null | undefined): string | null => {
  const trimmed = value?.trim();
  if (!trimmed) {
    return null;
  }
  return trimmed;
};

const survivorPickFromStamp = (suggestion: PendingMergeSuggestion): MergeSurvivorPick | null => {
  const survivorClusterId = suggestion.survivor_cluster_id;
  if (typeof survivorClusterId !== 'string' || survivorClusterId.length === 0) {
    return null;
  }
  const { cluster_a_id: clusterAId, cluster_b_id: clusterBId } = suggestion;
  if (survivorClusterId !== clusterAId && survivorClusterId !== clusterBId) {
    return null;
  }
  const unlabeledId = survivorClusterId === clusterAId ? clusterBId : clusterAId;
  const stampedLabel = trimLabel(suggestion.survivor_label);
  const sideLabel = trimLabel(
    survivorClusterId === clusterAId ? suggestion.cluster_a_label : suggestion.cluster_b_label,
  );
  const survivorLabel = stampedLabel ?? sideLabel;
  if (!survivorLabel || !isMeaningfulMergeLabel(survivorLabel)) {
    return null;
  }
  return { survivorClusterId, unlabeledId, survivorLabel };
};

const survivorPickFromLabels = (suggestion: PendingMergeSuggestion): MergeSurvivorPick | null => {
  const aLabeled = isMeaningfulMergeLabel(suggestion.cluster_a_label);
  const bLabeled = isMeaningfulMergeLabel(suggestion.cluster_b_label);
  if (aLabeled === bLabeled) {
    return null;
  }
  const survivorLabel = trimLabel(aLabeled ? suggestion.cluster_a_label : suggestion.cluster_b_label);
  if (!survivorLabel) {
    return null;
  }
  return {
    survivorClusterId: aLabeled ? suggestion.cluster_a_id : suggestion.cluster_b_id,
    unlabeledId: aLabeled ? suggestion.cluster_b_id : suggestion.cluster_a_id,
    survivorLabel,
  };
};

/**
 * Labeled-for-merge side: prefer backend `survivor_cluster_id` / `survivor_label`
 * (DATA-14). Fall back to `isMeaningfulMergeLabel` only when those fields are omitted.
 */
export const mergeSurvivorFromSuggestion = (
  suggestion: PendingMergeSuggestion,
): MergeSurvivorPick | null => survivorPickFromStamp(suggestion) ?? survivorPickFromLabels(suggestion);

/**
 * Pending (pre-accept) twin for an unlabeled-for-merge cluster. When the payload
 * stamps `survivor_cluster_id`, that id is the labeled side and the other id is
 * unlabeled even if both `cluster_*_label` strings are human-shaped. Both-labeled
 * and neither-labeled pairs without a stamp yield no chip.
 */
export const pendingMergeTwinForCluster = (
  clusterId: string | null,
  suggestions: readonly PendingMergeSuggestion[],
): PendingMergeTwin | null => {
  if (!clusterId) {
    return null;
  }

  for (const suggestion of suggestions) {
    if (suggestion.status !== 'pending') {
      continue;
    }
    const pick = mergeSurvivorFromSuggestion(suggestion);
    if (pick?.unlabeledId !== clusterId) {
      continue;
    }
    return {
      suggestionId: suggestion.id,
      survivorClusterId: pick.survivorClusterId,
      survivorLabel: pick.survivorLabel,
    };
  }

  return null;
};
