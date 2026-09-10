import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  createGuidedScenario,
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  GUIDED_NAME_CHOICE,
} from '../../../guidedPrototype/state';
import { GuidedDescriptionReview, type GuidedDescriptionReviewActions } from '../GuidedDescriptionReview';
import type { GuidedReviewState } from '../../../guidedPrototype/reviewDrafts';

const scenario = createGuidedScenario();
const appliedTribeca = scenario.pressPhotos[0]?.altText ?? '';
const appliedCoachella = scenario.pressPhotos[1]?.altText ?? '';

const perImageState = (): GuidedReviewState => ({
  choices: {
    left: GUIDED_NAME_CHOICE.INCLUDE,
    right: GUIDED_NAME_CHOICE.INCLUDE,
  },
  pendingChoiceChange: null,
  drafts: {
    tribeca: {
      draftText: scenario.samples.tribeca.both ?? null,
      draftOrigin: GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE,
      draftStatus: GUIDED_DRAFT_STATUS.READY,
      draftVersion: 1,
      previewedVersion: 1,
      appliedAltText: appliedTribeca,
      applicationHistory: [],
      draftHistory: [],
    },
    coachella: {
      draftText: scenario.samples.coachella.both ?? null,
      draftOrigin: GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE,
      draftStatus: GUIDED_DRAFT_STATUS.READY,
      draftVersion: 1,
      previewedVersion: 1,
      appliedAltText: appliedCoachella,
      applicationHistory: [],
      draftHistory: [],
    },
  },
});

const actions = (): GuidedDescriptionReviewActions => ({
  onEdit: vi.fn(),
  onDraftInput: vi.fn(),
  onPreview: vi.fn(),
  onKeep: vi.fn(),
  onRetryFixture: vi.fn(),
  onRestore: vi.fn(),
  onApply: vi.fn(),
  onUndo: vi.fn(),
});

describe('GuidedDescriptionReview per-image drafts', () => {
  it('renders one labelled editor and independent apply controls per photo', () => {
    const reviewActions = actions();
    render(<GuidedDescriptionReview scenario={scenario} state={perImageState()} actions={reviewActions} />);

    expect(screen.getAllByRole('article')).toHaveLength(2);
    expect(screen.getByRole('heading', { name: /Tribeca Festival/ })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Coachella festival/ })).toBeInTheDocument();
    const editors = screen.getAllByRole('textbox', { name: 'Alt text draft' });
    expect(editors[0]).toHaveAttribute('id', 'guided-description-draft-tribeca');
    expect(editors).toHaveLength(2);
    expect(screen.getByTestId('demo-apply-tribeca')).toBeEnabled();
    expect(screen.getByTestId('demo-apply-coachella')).toBeEnabled();
    expect(screen.getByTestId('demo-undo-tribeca')).toBeDisabled();
    expect(screen.getByTestId('demo-undo-coachella')).toBeDisabled();
  });

  it('sends image keys with preview and apply actions', () => {
    const reviewActions = actions();
    const initialState = perImageState();
    const { rerender } = render(
      <GuidedDescriptionReview scenario={scenario} state={initialState} actions={reviewActions} />,
    );

    const editors = screen.getAllByRole('textbox', { name: 'Alt text draft' });
    fireEvent.change(editors[1], { target: { value: 'Coachella edited locally.' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Preview the change' })[1]);

    const editedState = perImageState();
    const editedDraft = editedState.drafts?.coachella;
    if (editedDraft === undefined) {
      throw new Error('Expected a Coachella draft fixture.');
    }
    editedState.drafts = {
      ...editedState.drafts,
      coachella: {
        ...editedDraft,
        draftText: 'Coachella edited locally.',
        draftVersion: 2,
        previewedVersion: 2,
      },
    };
    rerender(<GuidedDescriptionReview scenario={scenario} state={editedState} actions={reviewActions} />);
    fireEvent.click(screen.getByTestId('demo-apply-coachella'));

    expect(reviewActions.onDraftInput).toHaveBeenCalledWith('coachella', 'Coachella edited locally.');
    expect(reviewActions.onPreview).toHaveBeenCalledWith('coachella', 'Coachella edited locally.');
    expect(reviewActions.onApply).toHaveBeenCalledWith('coachella', 'Coachella edited locally.');
    expect(reviewActions.onUndo).not.toHaveBeenCalled();
  });

  it('keeps a missing per-image fixture visible without inventing a description', () => {
    const state = perImageState();
    const coachellaDraft = state.drafts?.coachella;
    if (coachellaDraft === undefined) {
      throw new Error('Expected a Coachella draft fixture.');
    }
    state.drafts = {
      ...state.drafts,
      coachella: {
        ...coachellaDraft,
        draftText: null,
        draftStatus: GUIDED_DRAFT_STATUS.FIXTURE_MISSING,
      },
    };
    const reviewActions = actions();
    render(<GuidedDescriptionReview scenario={scenario} state={state} actions={reviewActions} />);

    expect(screen.getAllByRole('textbox', { name: 'Alt text draft' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Retry loading the sample' })).toHaveLength(1);
    expect(screen.getByTestId('guided-description-review-coachella')).toHaveTextContent(
      'The sample draft for these choices is unavailable.',
    );
  });
});
