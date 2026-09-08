export interface StoredFaceReviewTarget {
  suggestionId: string;
  identityCount?: number;
}

/** HAI-17: every multi-face stored identity requires a rendered review disclosure. */
export const requiresStoredFaceReview = (
  suggestion: Pick<StoredFaceReviewTarget, 'identityCount'>,
): boolean =>
  typeof suggestion.identityCount === 'number' &&
  Number.isInteger(suggestion.identityCount) &&
  suggestion.identityCount > 1;

/** Shared by single-card and selection commit paths. */
export const isStoredFaceApprovalBlocked = (
  suggestion: StoredFaceReviewTarget,
  reviewedSuggestionIds: ReadonlySet<string>,
): boolean =>
  requiresStoredFaceReview(suggestion) &&
  !reviewedSuggestionIds.has(suggestion.suggestionId);
