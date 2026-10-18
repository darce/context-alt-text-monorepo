import {
  compareSuggestions,
  isHumanLabeledTarget,
  type ProjectedSuggestion,
} from './suggestionProjection';

/** Review adapter always sets suggestionId from row.id; narrow for card/mutation consumers. */
export interface ReviewSuggestion extends ProjectedSuggestion {
  suggestionId: string;
}

export type SuggestionReviewItem =
  | {
      type: 'single';
      score: number;
      suggestion: ReviewSuggestion;
    }
  | {
      type: 'group';
      clusterId: string;
      score: number;
      label: string;
      suggestions: ReviewSuggestion[];
    };

const hasSuggestionId = (item: ProjectedSuggestion): item is ReviewSuggestion =>
  typeof item.suggestionId === 'string' && item.suggestionId.length > 0;

export const buildSuggestionReviewItems = (
  items?: readonly ProjectedSuggestion[],
): SuggestionReviewItem[] => {
  // Server already filters stricter; re-apply predicate + drop rows without suggestionId (no assert).
  const eligible = (items ?? []).filter(
    (item): item is ReviewSuggestion => hasSuggestionId(item) && isHumanLabeledTarget(item.label),
  );
  const sortedSuggestions = [...eligible].sort(compareSuggestions);
  const suggestionsByCluster = new Map<string, ReviewSuggestion[]>();

  for (const suggestion of sortedSuggestions) {
    const existing = suggestionsByCluster.get(suggestion.clusterId);
    if (existing) {
      existing.push(suggestion);
    } else {
      suggestionsByCluster.set(suggestion.clusterId, [suggestion]);
    }
  }

  const reviewItems: SuggestionReviewItem[] = [];
  for (const [clusterId, suggestions] of suggestionsByCluster.entries()) {
    const firstSuggestion = suggestions[0];
    const label = firstSuggestion.label ?? firstSuggestion.enrichment?.suggestedLabel ?? '';

    if (suggestions.length > 1 && label) {
      reviewItems.push({
        type: 'group',
        clusterId,
        label,
        suggestions,
        score: Math.max(...suggestions.map((suggestion) => suggestion.similarity)),
      });
      continue;
    }

    for (const suggestion of suggestions) {
      reviewItems.push({
        type: 'single',
        score: suggestion.similarity,
        suggestion,
      });
    }
  }

  return reviewItems.sort((a, b) => b.score - a.score);
};
