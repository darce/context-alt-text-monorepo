/**
 * HAI-15 session state for the review queue.
 *
 * This is deliberately browser-session state only. It is owned by the stable
 * ScanTabContent mount, so swapping the queue for a label/review panel does not
 * erase an operator's independent judgment or disclosure state. The parent
 * remounts it at the tenant boundary; nothing here claims localStorage or API
 * durability.
 */

export interface HAIReviewState {
  /** First independent name judgment per suggestion; never overwritten. */
  nameJudgments: ReadonlyMap<string, string>;
  /** NAME suggestions whose model output is currently disclosed. */
  revealedNameSuggestionIds: ReadonlySet<string>;
  /** ASSIGNMENT stored-face disclosures the operator has presented. */
  reviewedStoredFaceSuggestionIds: ReadonlySet<string>;
}

export const createEmptyHAIReviewState = (): HAIReviewState => ({
  nameJudgments: new Map(),
  revealedNameSuggestionIds: new Set(),
  reviewedStoredFaceSuggestionIds: new Set(),
});

export const recordFirstNameJudgment = (
  state: HAIReviewState,
  suggestionId: string,
  judgment: string,
): HAIReviewState => {
  const normalized = judgment.trim();
  if (!normalized || state.nameJudgments.has(suggestionId)) {
    return state;
  }

  return {
    ...state,
    nameJudgments: new Map(state.nameJudgments).set(suggestionId, normalized),
  };
};

export const toggleNameSuggestionReveal = (
  state: HAIReviewState,
  suggestionId: string,
): HAIReviewState => {
  if (!state.nameJudgments.has(suggestionId)) {
    return state;
  }

  const next = new Set(state.revealedNameSuggestionIds);
  if (next.has(suggestionId)) {
    next.delete(suggestionId);
  } else {
    next.add(suggestionId);
  }

  return { ...state, revealedNameSuggestionIds: next };
};

export const markStoredFaceReviewPresented = (
  state: HAIReviewState,
  suggestionId: string,
): HAIReviewState => {
  if (state.reviewedStoredFaceSuggestionIds.has(suggestionId)) {
    return state;
  }

  const next = new Set(state.reviewedStoredFaceSuggestionIds);
  next.add(suggestionId);
  return { ...state, reviewedStoredFaceSuggestionIds: next };
};
