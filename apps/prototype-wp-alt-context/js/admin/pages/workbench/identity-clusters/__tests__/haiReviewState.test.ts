import { describe, expect, it } from 'vitest';

import {
  createEmptyHAIReviewState,
  markStoredFaceReviewPresented,
  recordFirstNameJudgment,
  toggleNameSuggestionReveal,
} from '../haiReviewState';

describe('HAI-15 review state', () => {
  it('records only the first independent judgment', () => {
    const initial = createEmptyHAIReviewState();
    const recorded = recordFirstNameJudgment(initial, 'name-1', ' Alex ');
    const repeated = recordFirstNameJudgment(recorded, 'name-1', 'Jordan');

    expect(recorded.nameJudgments.get('name-1')).toBe('Alex');
    expect(repeated).toBe(recorded);
    expect(repeated.nameJudgments.get('name-1')).toBe('Alex');
  });

  it('only toggles disclosure after an independent judgment exists', () => {
    const initial = createEmptyHAIReviewState();
    expect(toggleNameSuggestionReveal(initial, 'name-1')).toBe(initial);

    const judged = recordFirstNameJudgment(initial, 'name-1', 'Alex');
    const revealed = toggleNameSuggestionReveal(judged, 'name-1');
    const hidden = toggleNameSuggestionReveal(revealed, 'name-1');

    expect(revealed.revealedNameSuggestionIds.has('name-1')).toBe(true);
    expect(hidden.revealedNameSuggestionIds.has('name-1')).toBe(false);
  });

  it('adds stored-face disclosures immutably', () => {
    const initial = createEmptyHAIReviewState();
    const reviewed = markStoredFaceReviewPresented(initial, 'assignment-1');

    expect(initial.reviewedStoredFaceSuggestionIds.has('assignment-1')).toBe(false);
    expect(reviewed.reviewedStoredFaceSuggestionIds.has('assignment-1')).toBe(true);
    expect(markStoredFaceReviewPresented(reviewed, 'assignment-1')).toBe(reviewed);
  });
});
