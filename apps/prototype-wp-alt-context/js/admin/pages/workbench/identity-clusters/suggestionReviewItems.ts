import type { PendingSuggestion } from '../../../api/recognition';
import type { SuggestionReviewItem } from './SuggestionCards';

export const buildSuggestionReviewItems = (assignmentSuggestions?: PendingSuggestion[]): SuggestionReviewItem[] => {
  const sortedSuggestions = [...(assignmentSuggestions ?? [])].sort(
    (a, b) => b.representative_similarity - a.representative_similarity,
  );
  const suggestionsByCluster = new Map<string, PendingSuggestion[]>();

  for (const suggestion of sortedSuggestions) {
    const existing = suggestionsByCluster.get(suggestion.suggested_cluster_id);
    if (existing) {
      existing.push(suggestion);
    } else {
      suggestionsByCluster.set(suggestion.suggested_cluster_id, [suggestion]);
    }
  }

  const items: SuggestionReviewItem[] = [];
  for (const [clusterId, suggestions] of suggestionsByCluster.entries()) {
    const firstSuggestion = suggestions[0];
    const label = firstSuggestion.cluster_label ?? firstSuggestion.suggested_label ?? '';

    if (suggestions.length > 1 && label) {
      items.push({
        type: 'group',
        clusterId,
        label,
        suggestions,
        score: Math.max(...suggestions.map((suggestion) => suggestion.representative_similarity)),
      });
      continue;
    }

    for (const suggestion of suggestions) {
      items.push({
        type: 'single',
        score: suggestion.representative_similarity,
        suggestion,
      });
    }
  }

  return items.sort((a, b) => b.score - a.score);
};
