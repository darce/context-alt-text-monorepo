import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { guidedCopy } from '../../../guidedPrototype/copy';
import {
  GUIDED_DRAFT_ORIGIN,
  GUIDED_DRAFT_STATUS,
  GUIDED_NAME_CHOICE,
  createGuidedDemoState,
  createGuidedScenario,
  type GuidedDemoState,
} from '../../../guidedPrototype/state';
import { GuidedDescriptionReview, type GuidedDescriptionReviewActions } from '../GuidedDescriptionReview';

vi.mock('../GuidedLiveDescriptionPanel', () => ({
  GuidedLiveDescriptionPanel: (): never => {
    throw new Error('unreachable guided live status');
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
});

const readyState = (
  draftText: string,
  draftOrigin: GuidedDemoState['draftOrigin'] = GUIDED_DRAFT_ORIGIN.RECORDED_SAMPLE,
): GuidedDemoState => {
  const base = createGuidedDemoState();
  return {
    ...base,
    choices: {
      left: GUIDED_NAME_CHOICE.INCLUDE,
      right: GUIDED_NAME_CHOICE.INCLUDE,
    },
    drafts: {
      tribeca: {
        ...base.drafts.tribeca,
        draftText,
        draftOrigin,
        draftStatus: GUIDED_DRAFT_STATUS.READY,
        draftVersion: 1,
        previewedVersion: 1,
      },
      coachella: base.drafts.coachella,
    },
  };
};

const reviewActions = (): GuidedDescriptionReviewActions => ({
  onEdit: vi.fn(),
  onDraftInput: vi.fn(),
  onPreview: vi.fn(),
  onKeep: vi.fn(),
  onRetryFixture: vi.fn(),
  onRestore: vi.fn(),
  onApply: vi.fn(),
  onUndo: vi.fn(),
});

describe('GuidedDescriptionReview editor', () => {
  it('uses a supplied label only for recorded samples, keeping edited origin distinct', () => {
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    const recordedLabel = 'Saved from the public recorded walkthrough.';
    const { rerender } = render(
      <GuidedDescriptionReview
        scenario={scenario}
        state={readyState('Recorded sample.')}
        actions={actions}
        recordedOriginLabel={recordedLabel}
      />,
    );

    expect(screen.getByText(recordedLabel)).toBeInTheDocument();

    rerender(
      <GuidedDescriptionReview
        scenario={scenario}
        state={readyState('Visitor edit.', GUIDED_DRAFT_ORIGIN.VISITOR_EDIT)}
        actions={actions}
        recordedOriginLabel={recordedLabel}
      />,
    );

    expect(screen.getByText(guidedCopy('draft.origin_edited'))).toBeInTheDocument();
    expect(screen.queryByText(recordedLabel)).not.toBeInTheDocument();
  });
});

describe('a failing live panel does not take the lesson with it', () => {
  it('keeps the draft, apply controls and demo copy on screen', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const { GuidedPrototypePage } = await import('../GuidedPrototypePage');
    const user = userEvent.setup();

    render(<GuidedPrototypePage />);

    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
    expect(screen.getByRole('heading', { name: guidedCopy('step.apply') })).toBeInTheDocument();
    fireEvent.click(
      within(screen.getByTestId('name-choice-tribeca-left')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Justin Trudeau' }),
      }),
    );
    fireEvent.click(
      within(screen.getByTestId('name-choice-tribeca-right')).getByRole('radio', {
        name: guidedCopy('names.include', { name: 'Katy Perry' }),
      }),
    );

    expect(screen.getByTestId('demo-apply-tribeca')).toBeInTheDocument();
    expect(screen.getByTestId('demo-applied-image-tribeca')).toBeInTheDocument();

    const edited = 'Draft still works after the live panel crashed.';
    const review = screen.getByTestId('guided-description-review-tribeca');
    const editor = within(review).getByRole('textbox', {
      name: guidedCopy('draft.label'),
    });
    fireEvent.change(editor, { target: { value: edited } });
    await user.click(within(review).getByRole('button', { name: guidedCopy('draft.next') }));
    await user.click(screen.getByTestId('demo-apply-tribeca'));

    expect(screen.getByTestId('demo-applied-image-tribeca')).toHaveAttribute('alt', edited);
    expect(screen.getByRole('alert')).toHaveTextContent(guidedCopy('live.failed'));
  });
});
