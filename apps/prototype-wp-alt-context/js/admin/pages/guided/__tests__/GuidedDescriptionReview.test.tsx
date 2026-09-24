import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import {
  createGuidedScenario,
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  GUIDED_NAME_CHOICE,
  GUIDED_OUTCOME,
} from '../../../guidedPrototype/state';
import { guidedCopy as publicGuidedCopy } from '../../../guidedPrototype/publicGuideCopy';
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

  it('keeps admin apply and Keep eligibility tied to the photo whose names were answered', () => {
    const reviewActions = actions();
    const state = perImageState();
    state.photoChoices = {
      tribeca: {
        left: GUIDED_NAME_CHOICE.INCLUDE,
        right: GUIDED_NAME_CHOICE.INCLUDE,
      },
      coachella: {
        left: GUIDED_NAME_CHOICE.INCLUDE,
        right: GUIDED_NAME_CHOICE.UNANSWERED,
      },
    };

    render(<GuidedDescriptionReview scenario={scenario} state={state} actions={reviewActions} />);

    const tribeca = screen.getByTestId('guided-description-review-tribeca');
    const coachella = screen.getByTestId('guided-description-review-coachella');
    expect(within(tribeca).getByTestId('demo-apply-tribeca')).toBeEnabled();
    expect(within(tribeca).getByTestId('guided-keep-current-tribeca')).toBeEnabled();
    expect(within(tribeca).queryByText(publicGuidedCopy('draft.blocked'))).not.toBeInTheDocument();
    expect(within(coachella).getByTestId('demo-apply-coachella')).toBeDisabled();
    expect(within(coachella).getByTestId('guided-keep-current-coachella')).toBeDisabled();
    expect(within(coachella).getAllByText(publicGuidedCopy('draft.blocked')).length).toBeGreaterThan(0);
  });

  it('shows the public empty state without controls and lets answered Coachella apply independently', () => {
    const reviewActions = actions();
    const state = perImageState();
    state.photoChoices = {
      tribeca: {
        left: GUIDED_NAME_CHOICE.UNANSWERED,
        right: GUIDED_NAME_CHOICE.INCLUDE,
      },
      coachella: {
        left: GUIDED_NAME_CHOICE.INCLUDE,
        right: GUIDED_NAME_CHOICE.LEAVE_UNNAMED,
      },
    };

    render(<GuidedDescriptionReview scenario={scenario} state={state} actions={reviewActions} scope="public" />);

    const tribeca = screen.getByTestId('guided-description-review-tribeca');
    const coachella = screen.getByTestId('guided-description-review-coachella');
    expect(within(tribeca).getByText(publicGuidedCopy('choices.help.public'))).toBeInTheDocument();
    expect(within(tribeca).queryByRole('button')).not.toBeInTheDocument();
    expect(within(tribeca).queryByRole('textbox')).not.toBeInTheDocument();
    expect(within(tribeca).queryByRole('alert')).not.toBeInTheDocument();
    expect(within(coachella).getByTestId('demo-apply-coachella')).toBeEnabled();
    expect(within(coachella).getByTestId('guided-keep-current-coachella')).toBeEnabled();
    expect(within(coachella).queryByText(publicGuidedCopy('error.no_recorded_draft.public'))).not.toBeInTheDocument();
  });

  it('uses the public review heading and gives the apply target real labelled section semantics', () => {
    const reviewActions = actions();
    render(
      <GuidedDescriptionReview scenario={scenario} state={perImageState()} actions={reviewActions} scope="public" />,
    );

    expect(
      screen.getByRole('heading', { level: 2, name: publicGuidedCopy('step.review.public') }),
    ).toBeInTheDocument();
    for (const imageKey of ['tribeca', 'coachella'] as const) {
      const review = screen.getByTestId(`guided-description-review-${imageKey}`);
      expect(
        within(review).getAllByRole('heading', {
          level: 4,
          name: publicGuidedCopy('step.review.public'),
        }),
      ).toHaveLength(1);
    }
    expect(screen.queryByRole('heading', { name: 'Edit the alt text' })).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Apply and undo' })).not.toBeInTheDocument();

    const applySection = document.getElementById('guided-section-apply');
    if (applySection === null) {
      throw new Error('Expected the per-image apply section.');
    }
    expect(applySection.tagName).toBe('SECTION');
    expect(applySection).toHaveAttribute('aria-labelledby', 'acx-guided-review-title');
    expect(applySection).toHaveAccessibleName(publicGuidedCopy('step.review.public'));

    for (const imageKey of ['tribeca', 'coachella'] as const) {
      const apply = screen.getByTestId(`guided-apply-${imageKey}`);
      expect(within(apply).getByTestId(`guided-image-status-${imageKey}`)).toBeInTheDocument();
      expect(within(apply).getByTestId(`guided-image-status-${imageKey}`).parentElement).toBe(apply);
    }
  });

  it('passes the latest public field value to image apply and announces it in that card', () => {
    const reviewActions = actions();
    reviewActions.onApplyForImage = vi.fn();
    const state = perImageState();
    const tribecaDraft = state.drafts?.tribeca;
    if (tribecaDraft === undefined) {
      throw new Error('Expected a Tribeca draft fixture.');
    }
    state.drafts = {
      ...state.drafts,
      tribeca: { ...tribecaDraft, previewedVersion: null },
    };
    const { rerender } = render(
      <GuidedDescriptionReview scenario={scenario} state={state} actions={reviewActions} scope="public" />,
    );

    const card = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(card).getByRole('textbox', { name: publicGuidedCopy('draft.field_label.public') });
    const visibleText = 'Latest public edit, applied without preview.';
    fireEvent.change(editor, { target: { value: visibleText } });

    const apply = within(card).getByTestId('demo-apply-tribeca');
    expect(apply).toBeEnabled();
    fireEvent.click(apply);

    expect(reviewActions.onApplyForImage).toHaveBeenCalledWith('tribeca', visibleText);
    expect(within(card).getByTestId('guided-image-status-tribeca')).toHaveTextContent(
      publicGuidedCopy('outcome.applied_image.public'),
    );

    const appliedState = perImageState();
    const appliedDraft = appliedState.drafts?.tribeca;
    if (appliedDraft === undefined) {
      throw new Error('Expected an applied Tribeca draft fixture.');
    }
    appliedState.drafts = {
      ...appliedState.drafts,
      tribeca: {
        ...appliedDraft,
        draftText: visibleText,
        draftVersion: 2,
        appliedAltText: visibleText,
        applicationHistory: [
          {
            previousAltText: appliedTribeca,
            appliedDraftVersion: 2,
            sequence: 1,
          },
        ],
      },
    };
    rerender(
      <GuidedDescriptionReview scenario={scenario} state={appliedState} actions={reviewActions} scope="public" />,
    );
    expect(within(card).getByTestId('demo-undo-tribeca')).toHaveFocus();
    expect(within(card).queryByTestId('demo-applied-image-tribeca')).not.toBeInTheDocument();
  });

  it('announces when the public reader keeps the current description', () => {
    const reviewActions = actions();
    reviewActions.onKeepForImage = vi.fn();
    render(
      <GuidedDescriptionReview scenario={scenario} state={perImageState()} actions={reviewActions} scope="public" />,
    );

    const card = screen.getByTestId('guided-description-review-coachella');
    fireEvent.click(within(card).getByTestId('guided-keep-current-coachella'));

    expect(reviewActions.onKeepForImage).toHaveBeenCalledWith('coachella');
    expect(within(card).getByTestId('guided-image-status-coachella')).toHaveTextContent(
      publicGuidedCopy('outcome.kept_body.public'),
    );
    expect(within(card).queryByText(publicGuidedCopy('error.unchanged_draft.public'))).not.toBeInTheDocument();
  });

  it('disables Keep after Use and enables it again after Undo', () => {
    const reviewActions = actions();
    reviewActions.onApplyForImage = vi.fn();
    reviewActions.onUndoForImage = vi.fn();
    const state = perImageState();
    state.photoChoices = {
      tribeca: {
        left: GUIDED_NAME_CHOICE.INCLUDE,
        right: GUIDED_NAME_CHOICE.INCLUDE,
      },
      coachella: {
        left: GUIDED_NAME_CHOICE.INCLUDE,
        right: GUIDED_NAME_CHOICE.INCLUDE,
      },
    };
    const { rerender } = render(
      <GuidedDescriptionReview scenario={scenario} state={state} actions={reviewActions} scope="public" />,
    );
    const card = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(card).getByRole('textbox', { name: publicGuidedCopy('draft.field_label.public') });
    const editedDescription = 'An edited description used for this photo.';
    fireEvent.change(editor, { target: { value: editedDescription } });
    fireEvent.click(within(card).getByTestId('demo-apply-tribeca'));

    expect(reviewActions.onApplyForImage).toHaveBeenCalledWith('tribeca', editedDescription);

    const appliedState = perImageState();
    const tribecaDraft = appliedState.drafts?.tribeca;
    if (tribecaDraft === undefined) {
      throw new Error('Expected an applied Tribeca draft fixture.');
    }
    appliedState.photoChoices = state.photoChoices;
    appliedState.drafts = {
      ...appliedState.drafts,
      tribeca: {
        ...tribecaDraft,
        draftText: editedDescription,
        draftVersion: 2,
        appliedAltText: editedDescription,
        outcome: GUIDED_OUTCOME.APPLIED,
        applicationHistory: [
          {
            previousAltText: appliedTribeca,
            appliedDraftVersion: 2,
            sequence: 1,
          },
        ],
      },
    };
    const appliedTribecaDraft = appliedState.drafts.tribeca;
    if (appliedTribecaDraft === undefined) {
      throw new Error('Expected the applied Tribeca draft.');
    }
    rerender(
      <GuidedDescriptionReview scenario={scenario} state={appliedState} actions={reviewActions} scope="public" />,
    );

    expect(within(card).getByTestId('guided-keep-current-tribeca')).toBeDisabled();
    expect(within(card).getByTestId('demo-undo-tribeca')).toBeEnabled();

    fireEvent.click(within(card).getByTestId('demo-undo-tribeca'));
    expect(reviewActions.onUndoForImage).toHaveBeenCalledWith('tribeca');

    const undoneState: GuidedReviewState = {
      ...appliedState,
      drafts: {
        ...appliedState.drafts,
        tribeca: {
          ...appliedTribecaDraft,
          appliedAltText: appliedTribeca,
          outcome: GUIDED_OUTCOME.NOT_FINISHED,
          applicationHistory: [],
        },
      },
    };
    rerender(
      <GuidedDescriptionReview scenario={scenario} state={undoneState} actions={reviewActions} scope="public" />,
    );

    expect(within(card).getByTestId('guided-keep-current-tribeca')).toBeEnabled();
    expect(within(card).getByTestId('demo-undo-tribeca')).toBeDisabled();
  });

  it('clears a public card status when reset replaces its draft state', () => {
    const reviewActions = actions();
    reviewActions.onApplyForImage = vi.fn();
    const state = perImageState();
    const { rerender } = render(
      <GuidedDescriptionReview scenario={scenario} state={state} actions={reviewActions} scope="public" />,
    );
    const card = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(card).getByRole('textbox', { name: publicGuidedCopy('draft.field_label.public') });
    fireEvent.change(editor, { target: { value: 'A public status that reset must clear.' } });
    fireEvent.click(within(card).getByTestId('demo-apply-tribeca'));
    expect(within(card).getByTestId('guided-image-status-tribeca')).toHaveTextContent(
      publicGuidedCopy('outcome.applied_image.public'),
    );

    const resetState = perImageState();
    resetState.choices = {
      left: GUIDED_NAME_CHOICE.UNDECIDED,
      right: GUIDED_NAME_CHOICE.UNDECIDED,
    };
    const resetTribecaDraft = resetState.drafts?.tribeca;
    if (resetTribecaDraft === undefined) {
      throw new Error('Expected a reset Tribeca draft fixture.');
    }
    resetState.drafts = {
      ...resetState.drafts,
      tribeca: {
        ...resetTribecaDraft,
        draftText: null,
        draftStatus: GUIDED_DRAFT_STATUS.BLOCKED,
        draftVersion: 0,
        previewedVersion: null,
        applicationHistory: [],
      },
    };
    rerender(<GuidedDescriptionReview scenario={scenario} state={resetState} actions={reviewActions} scope="public" />);

    expect(screen.queryByTestId('guided-image-status-tribeca')).not.toBeInTheDocument();
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
