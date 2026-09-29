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
  it('remeasures height from content after edits, window resizes, and description changes', () => {
    let contentHeight = 0;
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    const { rerender } = render(
      <GuidedDescriptionReview scenario={scenario} state={readyState('A saved draft.')} actions={actions} />,
    );
    const editor = within(screen.getByTestId('guided-description-review-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.label'),
    });
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      get: () => contentHeight,
    });
    Object.assign(editor.style, {
      boxSizing: 'border-box',
      borderTop: '2px solid black',
      borderBottom: '3px solid black',
    });
    const borderHeight =
      Number.parseFloat(window.getComputedStyle(editor).borderTopWidth) +
      Number.parseFloat(window.getComputedStyle(editor).borderBottomWidth);

    contentHeight = 180;
    fireEvent.input(editor);
    expect(editor.style.height).toBe(`${editor.scrollHeight + borderHeight}px`);

    contentHeight = 420;
    fireEvent(window, new Event('resize'));
    expect(editor.style.height).toBe(`${editor.scrollHeight + borderHeight}px`);

    contentHeight = 640;
    rerender(
      <GuidedDescriptionReview
        scenario={scenario}
        state={readyState('A replacement saved description.')}
        actions={actions}
      />,
    );
    expect(editor.style.height).toBe(`${editor.scrollHeight + borderHeight}px`);
    expect(actions.onPreview).not.toHaveBeenCalled();
  });

  it('includes computed border widths in the content height', () => {
    const scenario = createGuidedScenario();
    const actions = reviewActions();
    render(
      <GuidedDescriptionReview scenario={scenario} state={readyState('A saved draft.')} actions={actions} />,
    );
    const editor = within(screen.getByTestId('guided-description-review-tribeca')).getByRole('textbox', {
      name: guidedCopy('draft.label'),
    });
    const contentHeight = 220;
    Object.defineProperty(editor, 'scrollHeight', {
      configurable: true,
      value: contentHeight,
    });
    Object.assign(editor.style, {
      boxSizing: 'border-box',
      borderTop: '2px solid black',
      borderBottom: '3px solid black',
    });
    const computedStyle = window.getComputedStyle(editor);
    const expectedHeight =
      editor.scrollHeight +
      Number.parseFloat(computedStyle.borderTopWidth) +
      Number.parseFloat(computedStyle.borderBottomWidth);

    fireEvent.input(editor);

    expect(editor.style.height).toBe(`${expectedHeight}px`);
  });

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
